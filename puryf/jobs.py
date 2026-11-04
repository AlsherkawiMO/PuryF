# SPDX-License-Identifier: MIT
"""Thread-safe in-process job coordinator used by all PuryF adapters.

One FIFO and one dedicated Office-compatible worker serialize conversion and
PDF-tool jobs. COM initialization, Office calls and COM cleanup stay on that
worker. No GUI callbacks are executed here. Cross-process/HTTP/MCP transports
are adapter work; they should submit to the owner of this service.
"""
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import queue
import threading
import time
import uuid

from . import engine as converters
from .engine import ConversionCancelled, QueueItem
from .options import ConversionOptions
from . import pdf_tools
from .explorer import InstanceLock, runtime_dir

TERMINAL = frozenset({"succeeded", "partial", "failed", "cancelled", "skipped"})


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _Job:
    id: str
    operation: str
    origin: str
    items: list
    options: ConversionOptions = field(repr=False)
    parameters: dict = field(default_factory=dict, repr=False)
    passwords: dict = field(default_factory=dict, repr=False)
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    logs: deque = field(default_factory=lambda: deque(maxlen=200))
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    report: str | None = None
    public_options: dict = field(default_factory=dict)


class JobHandle:
    def __init__(self, service, job_id):
        self.service = service
        self.id = job_id

    def snapshot(self):
        return self.service.get_job(self.id)

    def wait(self, timeout=None):
        return self.service.wait(self.id, timeout)

    def cancel(self):
        return self.service.cancel(self.id)

    def is_alive(self):
        return self.snapshot()["status"] not in TERMINAL


class ConversionService:
    """Own one FIFO, one worker and one job registry.

    Use get_default_service() to share the coordinator inside an application.
    Explicit instances are independent owners (useful for isolated servers/tests).
    Always close a service, preferably using a with block.
    """

    def __init__(self, reports_dir=None, *, engine_factory=None):
        self.reports_dir = Path(reports_dir) if reports_dir is not None else converters.REPORTS_DIR
        self._engine_factory = engine_factory or converters.ConverterEngine
        self._lock = threading.RLock()
        self._jobs = {}
        self._fifo = queue.Queue()
        self._listeners = set()
        self._worker = None
        self._accepting = True
        self._source_paths = set()
        self._run_allowed = threading.Event()
        self._run_allowed.set()

    @property
    def paused(self):return not self._run_allowed.is_set()

    def pause(self):self._run_allowed.clear()

    def resume(self):self._run_allowed.set()

    def _pause_boundary(self, job):
        while not self._run_allowed.wait(.1):
            if job.cancel.is_set():break

    @property
    def closed(self):
        with self._lock:
            return not self._accepting

    @property
    def busy(self):
        with self._lock:
            return any(j.status not in TERMINAL for j in self._jobs.values())

    def subscribe(self):
        """Return a private event queue. Read snapshots for events sent before subscribing."""
        events = queue.Queue()
        with self._lock:
            self._listeners.add(events)
        return events

    def unsubscribe(self, events):
        with self._lock:
            self._listeners.discard(events)

    def _emit(self, kind, job, **payload):
        # Call under the re-entrant service lock; copies isolate consumers.
        event = {"type": kind, "job_id": job.id, "operation": job.operation, **payload}
        for listener in self._listeners:
            listener.put_nowait(deepcopy(event))

    @staticmethod
    def _redact(job, text):
        for secret in [job.options.pdf_password, *job.passwords.values()]:
            if secret:
                text = str(text).replace(secret, "[redacted]")
        return str(text)

    def _log(self, job, text):
        with self._lock:
            message = self._redact(job, text)
            job.logs.append(message)
            self._emit("log", job, message=message)

    def _error(self, job, code, message, item_id=None):
        with self._lock:
            error = {"code": code, "message": self._redact(job, message), "item_id": item_id}
            job.errors.append(error)
            self._emit("error", job, error=error)
            return deepcopy(error)

    def _item(self, job, item, status, output="", message="", seconds=0.0, code=None):
        with self._lock:
            item.status = status
            item.output = str(output)
            item.message = self._redact(job, message)
            item.seconds = seconds
            error = self._error(job, code, message, item.uid) if code else None
            self._emit("item_updated", job, item=self._item_snapshot(item, error))

    @staticmethod
    def _item_snapshot(item, error=None):
        return {"id": item.uid, "source": str(item.source), "status": item.status,
                "output": item.output or None, "message": item.message,
                "seconds": item.seconds, "error": deepcopy(error)}

    def _progress(self, job, completed, total, current=""):
        with self._lock:
            job.progress = {"completed": completed, "total": total,
                            "percent": round(completed * 100 / total) if total else 0,
                            "current": current}
            self._emit("progress", job, progress=job.progress)

    def _output(self, job, path, kind="converted", item_id=None, details=None):
        with self._lock:
            output = {"path": str(path), "kind": kind, "item_id": item_id}
            if details is not None:output["details"]=details
            job.outputs.append(output)
            self._emit("output_ready", job, output=output)

    def _submit(self, operation, sources, options=None, *, origin="library", item_ids=None,
                parameters=None, passwords=None):
        options = ConversionOptions.from_mapping(options)
        if operation != "convert" and (options.merge_pdf or options.compress_pdf or options.ocr_pdf):
            raise ValueError("Merge/split jobs accept protection and overwrite options; conversion post-processing requires a conversion job")
        if options.source_root:
            from dataclasses import replace
            options=replace(options,source_root=str(Path(options.source_root).expanduser().resolve()))
        if options.output_folder:
            from dataclasses import replace
            options = replace(options, output_folder=str(Path(options.output_folder).expanduser().resolve()))
        if isinstance(sources, (str, Path)):
            sources = [sources]
        paths = [Path(s).expanduser().resolve() for s in sources]
        if not paths:
            raise ValueError("A job must contain at least one input")
        if not isinstance(origin, str) or not origin.strip():
            raise ValueError("origin must be a nonempty string")
        if item_ids is not None and (len(item_ids) != len(paths) or
                any(not isinstance(i, str) or not i for i in item_ids) or len(set(item_ids)) != len(paths)):
            raise ValueError("item_ids must be unique and match the input count")
        normalized_passwords = {}
        for path, password in dict(passwords or {}).items():
            if not isinstance(password, str):
                raise ValueError("PDF passwords must be strings")
            normalized_passwords[str(Path(path).expanduser().resolve())] = password
        items = [QueueItem(path, uid=item_ids[n] if item_ids else uuid.uuid4().hex)
                 for n, path in enumerate(paths)]
        job = _Job(uuid.uuid4().hex, operation, origin, items, options,
                   dict(parameters or {}), normalized_passwords)
        job.public_options = options.public_settings()
        job.progress = {"completed": 0, "total": len(items), "percent": 0, "current": ""}
        with self._lock:
            if not self._accepting:
                raise RuntimeError("Conversion service is closed")
            self._jobs[job.id] = job
            self._source_paths.update(self._path_key(p) for p in paths)
            self._emit("job_submitted", job, status="queued")
            self._fifo.put(job)
            if self._worker is None:
                self._worker = threading.Thread(target=self._worker_loop, name="PuryF-OfficeWorker", daemon=True)
                self._worker.start()
        return JobHandle(self, job.id)

    def submit_conversion(self, sources, options=None, *, origin="library", item_ids=None):
        return self._submit("convert", sources, options, origin=origin, item_ids=item_ids)

    def submit_document(self, sources, spec, options=None, *, origin="library", password="", passwords=None):
        from .documents import validate_spec
        if isinstance(sources,(str,Path)):sources=[sources]
        sources=list(sources)
        spec=validate_spec(spec,len(sources))
        return self._submit("document",sources,options,origin=origin,parameters=spec,
            passwords=passwords or {str(p):password for p in sources})

    def submit_merge(self, sources, output_file, options=None, *, passwords=None, origin="library"):
        output = str(Path(output_file).expanduser().resolve())
        return self._submit("merge", sources, options, origin=origin, passwords=passwords,
                            parameters={"output_file": output})

    def submit_split(self, source, options=None, *, output_file=None, output_dir=None,
                     page_ranges=None, every_n=None, password="", origin="library"):
        if every_n is None:
            if not isinstance(page_ranges, str) or not page_ranges.strip() or not output_file:
                raise ValueError("Page-range split requires page_ranges and output_file")
            if output_dir is not None:
                raise ValueError("Page-range split does not accept output_dir")
        else:
            if isinstance(every_n, bool) or not isinstance(every_n, int) or every_n < 1 or not output_dir:
                raise ValueError("Interval split requires a positive every_n and output_dir")
            if output_file is not None or page_ranges is not None:
                raise ValueError("Interval split cannot include page_ranges or output_file")
        parameters = {"output_file": str(Path(output_file).resolve()) if output_file else None,
                      "output_dir": str(Path(output_dir).resolve()) if output_dir else None,
                      "page_ranges": page_ranges, "every_n": every_n}
        return self._submit("split", [source], options, origin=origin, passwords={str(source): password}, parameters=parameters)

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs[job_id]
            errors = {e["item_id"]: e for e in job.errors if e["item_id"]}
            return {"schema_version": 1, "id": job.id, "operation": job.operation, "origin": job.origin,
                    "status": job.status, "created_at": job.created_at, "started_at": job.started_at,
                    "finished_at": job.finished_at, "options": dict(job.public_options),
                    "parameters": deepcopy(job.parameters), "progress": dict(job.progress),
                    "inputs": [self._item_snapshot(i, errors.get(i.uid)) for i in job.items],
                    "outputs": deepcopy(job.outputs), "errors": deepcopy(job.errors),
                    "logs": list(job.logs), "report": job.report,
                    "cancel_requested": job.cancel.is_set()}

    def list_jobs(self):
        with self._lock:
            return [self.get_job(key) for key in self._jobs]

    def forget(self, job_id):
        """Remove terminal history after an adapter's retention period."""
        with self._lock:
            if self._jobs[job_id].status not in TERMINAL:
                raise ValueError("Cannot forget an active job")
            del self._jobs[job_id]
            self._source_paths = {self._path_key(i.source) for j in self._jobs.values() for i in j.items}

    def wait(self, job_id, timeout=None):
        with self._lock:
            done = self._jobs[job_id].done
        if not done.wait(timeout):
            raise TimeoutError(f"Job {job_id} is still running or queued")
        return self.get_job(job_id)

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs[job_id]
            if job.status in TERMINAL:
                return False
            job.cancel.set()
            if job.status == "queued":
                for item in job.items:
                    self._item(job, item, "Cancelled", message="Cancelled before starting")
                self._finish(job, "cancelled")
            else:
                job.status = "cancelling"
                self._emit("job_state", job, status="cancelling")
            return True

    @staticmethod
    def _path_key(path):
        return str(Path(path).resolve()).casefold()

    def _worker_loop(self):
        while True:
            job = self._fifo.get()
            lease = None
            try:
                if job is None:
                    return
                self._pause_boundary(job)
                # Each host has a FIFO; this per-user OS lease prevents a CLI
                # and desktop (or two CLIs) running converters concurrently.
                lease = InstanceLock(runtime_dir().parent / "Conversion")
                try:
                    notified = False
                    while not lease.acquire():
                        if not notified:
                            self._log(job, "Waiting for another PuryF conversion process")
                            notified = True
                        if job.cancel.wait(.1):
                            break
                except OSError as error:
                    with self._lock:
                        self._error(job, "worker_error", "Cannot acquire conversion lease: " + str(error))
                        self._finish(job, "failed")
                    continue
                with self._lock:
                    if job.status in TERMINAL:
                        continue
                    job.status = "running"
                    job.started_at = _now()
                    self._emit("job_state", job, status="running")
                try:
                    if job.operation == "convert":
                        self._convert(job)
                    elif job.operation == "document":
                        self._document_job(job)
                    else:
                        self._pdf_job(job)
                except Exception as error:
                    self._error(job, "worker_error", str(error))
                    for item in job.items:
                        if item.status in ("Queued", "Running"):
                            self._item(job, item, "Failed", message=str(error))
                finally:
                    with self._lock:
                        if job.cancel.is_set():
                            status = "cancelled"
                        elif job.errors:
                            status = "partial" if job.outputs else "failed"
                        elif all(i.status == "Skipped" for i in job.items):
                            status = "skipped"
                        else:
                            status = "succeeded"
                        self._finish(job, status)
            finally:
                if lease is not None:
                    lease.close()
                self._fifo.task_done()

    def _finish(self, job, status):
        job.status = status
        job.finished_at = _now()
        # Do not retain plaintext secrets in terminal job records.
        from dataclasses import replace
        if job.options.pdf_password:
            job.options = replace(job.options, password_pdf=False, pdf_password="")
        job.passwords.clear()
        self._emit("job_finished", job, status=status)
        job.done.set()

    def _check_source(self, path):
        if not path.is_file():
            return "missing_source", "Source file does not exist or is not a regular file"
        if path.suffix.lower() not in converters.ALL_EXTS:
            return "unsupported_format", f"Unsupported input format: {path.suffix or '(none)'}"
        return None

    def check_dependencies(self, sources, options=None):
        options = ConversionOptions.from_mapping(options)
        engine = self._new_engine(options, lambda text: None, threading.Event())
        if isinstance(sources, (str, Path)):
            sources = [sources]
        results = []
        for source in sources:
            path = Path(source).expanduser().resolve()
            issue = self._check_source(path)
            problems = engine.requirements(path)
            if issue:
                problems.insert(0, issue[1])
            results.append({"source": str(path), "ready": not problems, "issues": problems})
        return results

    def _new_engine(self, options, log, cancel):
        return self._engine_factory(options.engine_settings(), log, lambda *args: None,
                                    lambda *args: None, cancel, reports_dir=self.reports_dir)

    def _convert(self, job):
        engine = self._new_engine(job.options, lambda text: self._log(job, text), job.cancel)
        engine.commit_guard = self._commit_guard
        try:
            for index, item in enumerate(job.items, 1):
                self._pause_boundary(job)
                if job.cancel.is_set():
                    self._item(job, item, "Cancelled", message="Cancelled before starting")
                    continue
                started = time.monotonic()
                self._item(job, item, "Running")
                issue = self._check_source(item.source)
                requirements = engine.requirements(item.source) if not issue else []
                if issue or requirements:
                    code, message = issue or ("dependency_missing", "; ".join(requirements))
                    self._item(job, item, "Failed", message=message, code=code)
                    self._progress(job, index, len(job.items), item.source.name)
                    continue
                # Include sources belonging to every known job, not just this batch.
                with self._lock:
                    engine.source_paths = set(self._source_paths)
                try:
                    engine.input_index=index
                    output = engine.convert(item.source)
                    self._item(job, item, "Success", output, f"{time.monotonic()-started:.2f}s", time.monotonic()-started)
                    self._output(job, output, item_id=item.uid)
                except ConversionCancelled as error:
                    self._item(job, item, "Cancelled", message=str(error))
                    job.cancel.set()
                except FileExistsError as error:
                    self._item(job, item, "Skipped", message=str(error))
                except Exception as error:
                    self._item(job, item, "Failed", message=str(error), code="conversion_failed")
                self._progress(job, index, len(job.items), item.source.name)
            if job.options.merge_pdf and engine.generated and not job.cancel.is_set():
                try:
                    self._output(job, engine.merge_generated(), kind="merged")
                except ConversionCancelled:
                    job.cancel.set()
                    self._log(job, "Post-conversion merge cancelled")
                except Exception as error:
                    self._error(job, "merge_failed", str(error))
            try:
                report = engine.write_report(job.items)
                with self._lock:
                    job.report = str(report)
            except Exception as error:
                self._error(job, "report_failed", str(error))
        finally:
            # All Office objects are owned and released by this same worker.
            engine.quit_all()
            if engine.merge_temp is not None:
                engine.merge_temp.cleanup()
                engine.merge_temp = None

    def _document_job(self, job):
        from .documents import run
        paths=[i.source for i in job.items]
        try:
            for item in job.items:self._item(job,item,'Running')
            for path,details in run(paths,job.parameters,job.options,job.cancel,job.passwords,
                    lambda n,total,current:self._progress(job,n,total,current),self._commit_guard):
                self._output(job,path,'document',details=details)
            for item in job.items:self._item(job,item,'Success')
        except ConversionCancelled as error:
            job.cancel.set()
            for item in job.items:self._item(job,item,'Cancelled',message=str(error))
        except Exception as error:
            for item in job.items:self._item(job,item,'Failed',message=str(error),code='document_failed')

    def _pdf_job(self, job):
        paths = [i.source for i in job.items]
        for item in job.items:
            if not item.source.is_file() or item.source.suffix.lower() != ".pdf":
                self._item(job, item, "Failed", message="PDF source file required", code="invalid_pdf_source")
        if job.errors:
            for item in job.items:
                if item.status == "Queued":
                    self._item(job, item, "Failed", message="PDF batch contains an invalid input")
            return
        for item in job.items:
            self._item(job, item, "Running")
        try:
            if job.operation == "merge":
                output = job.parameters["output_file"]
                self._protect_destination(output)
                result = pdf_tools.merge(paths, output, job.options, job.cancel, job.passwords,
                                         lambda n, total, current: self._progress(job, n, total, current), self._commit_guard)
                self._output(job, result, "merged")
                for item in job.items:
                    self._item(job, item, "Success", result)
            else:
                params = dict(job.parameters)
                if params.get("output_file"):
                    self._protect_destination(params["output_file"])
                # The generator checks each part too; interval outputs are known before writing.
                for result in pdf_tools.split(paths[0], job.options, job.cancel,
                        password=job.passwords.get(str(paths[0]), ""),
                        commit_guard=self._commit_guard,
                        progress=lambda n, total, current: self._progress(job, n, total, current), **params):
                    self._output(job, result, "split")
                self._item(job, job.items[0], "Success", job.outputs[-1]["path"] if job.outputs else "")
        except ConversionCancelled as error:
            job.cancel.set()
            for item in job.items:
                self._item(job, item, "Cancelled", message=str(error))
        except Exception as error:
            code = "output_exists" if isinstance(error, FileExistsError) else "pdf_operation_failed"
            for item in job.items:
                self._item(job, item, "Failed", message=str(error), code=code)

    def _protect_destination(self, path):
        with self._lock:
            if self._path_key(path) in self._source_paths:
                raise ValueError("Output must not replace any queued source file")

    @contextmanager
    def _commit_guard(self, path):
        # Submission and the final atomic commit cannot race over a new source path.
        with self._lock:
            self._protect_destination(path)
            yield

    def close(self, wait=True):
        with self._lock:
            if self._accepting:
                self._accepting = False
                for job in self._jobs.values():
                    if job.status not in TERMINAL:
                        self.cancel(job.id)
                self._fifo.put(None)
            worker = self._worker
        if wait and worker and threading.current_thread() is not worker:
            worker.join()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


_default_lock = threading.Lock()
_default_service = None


def get_default_service(reports_dir=None):
    """One owner per process. Future transports forward requests to this owner."""
    global _default_service
    with _default_lock:
        if (_default_service is not None and _default_service.closed and
                _default_service._worker is not None and _default_service._worker.is_alive()):
            raise RuntimeError("The previous conversion service is still shutting down")
        if _default_service is None or _default_service.closed:
            _default_service = ConversionService(reports_dir=reports_dir)
        return _default_service
