# V1 additions

All conversion and PDF Studio writes run through JobService's coordinated FIFO worker.
Desktop, SDK, automation and CLI share that service contract; API/MCP retain the same
conversion engine and protected output commits. A per-user lease coordinates processes.
PDFium preview rendering uses a separate bounded pool and serialized PDFium access.

- documents.py: non-destructive PDF operations and PDFium rendering.
- state.py: local SQLite presets, bounded history, watch ledger and schedule claims.
- sdk.py: public Client, history tracking and repeat protection.
- automation.py: explicit watch/schedule configuration and background control mailbox.
- extensions.py: explicitly trusted local Python converter plugins.
- studio.py/workbench.py/i18n.py: desktop editing, automation and primary RTL controls.
- selftest.py/install_support.py: frozen runtime validation and installer maintenance.

Private passwords remain transient. History omits document text, passwords and raw logs;
protected jobs require fresh password options instead of silently replaying without protection.
A plugin runs with the local user's permissions and must be trusted. Server modes reject
CLI plugin loading. Hosted/public process isolation is still a deployment requirement.

# Shared conversion foundation — 0.2.0-alpha.1

## Components

| Module | Responsibility |
| --- | --- |
| `PuryF.py` | Desktop launcher; lazy compatibility exports for the previous module |
| `puryf/engine.py` | Headless conversion backends, format requirements and safe output writes |
| `puryf/options.py` | Immutable validated `ConversionOptions` |
| `puryf/jobs.py` | Job registry, FIFO, Office-owning worker, events and cancellation |
| `puryf/pdf_tools.py` | Headless PDF inspection, merging, splitting and encryption |
| `puryf/desktop.py` | Tk widgets, dialogs, session state and event rendering |

Importing `puryf` or the compatibility launcher never loads Tkinter. The headless regression test
explicitly blocks Tkinter imports, then performs a real text-to-PDF conversion.
All formats from the earlier engine remain present; external requirements are unchanged.

## Adapter contract

Explorer, CLI, MCP and HTTP adapters should validate their transport-specific inputs and pass requests
to the same service owner. They must not create their own engine or Office objects for every request.
The desktop already follows this path for batch conversion and its manual PDF tools.

```python
from puryf import ConversionOptions, get_default_service

service = get_default_service()
events = service.subscribe()
handle = service.submit_conversion(
    [r"C:\Documents\notes.txt", r"C:\Documents\photo.jpg"],
    ConversionOptions(output_folder=r"C:\Documents\PDFs"),
    origin="library",
)

snapshot = handle.snapshot()       # Nonblocking; JSON-serializable copy
result = handle.wait(timeout=60)   # Raises TimeoutError if still pending
print(result["status"], result["outputs"])

service.unsubscribe(events)
service.close()                    # Only the host/owner shuts the shared service down
```

For a self-contained script, use `with ConversionService(...) as service:` instead.
Closing a service requests cancellation and, by default, waits for its worker to finish.
Do not close the shared owner after each API/MCP request. No worker thread is started until the first job.

### Operations

- `submit_conversion(sources, options, origin=..., item_ids=...)`
- `submit_merge(sources, output_file, options, passwords=..., origin=...)`
- `submit_split(source, options, output_file=..., page_ranges=..., password=..., origin=...)`
- `submit_split(source, options, output_dir=..., every_n=..., password=..., origin=...)`
- `check_dependencies(sources, options)`
- `get_job(id)`, `list_jobs()`, `wait(id, timeout)`, `cancel(id)`
- `subscribe()`, `unsubscribe(queue)`, `close(wait=True)`

`options` may be a `ConversionOptions` object or a mapping with known fields. Invalid options are rejected
before the job is queued. Input and output paths are resolved at submission. Input order is preserved;
deliberate duplicate inputs remain allowed, with distinct item IDs and output collision handling.
Merge/split accept password protection and overwrite behavior; they reject conversion-only
merge/compression/OCR post-processing flags rather than silently ignoring them.

## Jobs and events

Public snapshots include a schema version, job ID, operation, origin, timestamps, accepted options,
progress, per-input states, output paths, report path, structured errors and recent log messages.
Copies are detached from service state, so changing a returned dictionary does not alter a job.

Job states: `queued`, `running`, `cancelling`, then `succeeded`, `partial`, `failed`, `skipped` or `cancelled`.
Item states retain the desktop labels: Queued, Running, Success, Failed, Skipped, Cancelled.
Progress reports completed work units; a split job's units are output parts, while conversion uses files.
A 100% work count is not a promise of success; the terminal job state and item errors determine that.

Event types: `job_submitted`, `job_state`, `item_updated`, `progress`, `output_ready`, `log`, `error`,
`job_finished`. Each event includes its job ID and operation. Each subscriber receives its own queue and
detached payload. Events are not replayed; read a snapshot when reconnecting. UI consumers drain their
queue on the UI thread; core workers never call Tk or run client callbacks.

Representative error codes include `missing_source`, `unsupported_format`, `dependency_missing`,
`conversion_failed`, `merge_failed`, `report_failed`, `invalid_pdf_source`, `output_exists`,
`pdf_operation_failed` and `worker_error`.

PDF passwords are excluded from snapshots/events, hidden in options representations, redacted from
worker messages, and cleared from terminal job records. Accepted public option flags remain available
after completion. Caller-owned option objects may still contain caller-supplied secrets.

## Queue and Office ownership

One service has one FIFO and one `PuryF-OfficeWorker` thread. All jobs are serialized through that worker,
including non-Office and PDF-tool jobs. This intentionally prioritizes predictable file handling and
Office thread ownership over parallel throughput. Office initialization, calls, application cleanup
and COM uninitialization all happen on that worker; no COM object is sent to an adapter or UI thread.
Office ownership is verified using an instrumented backend; actual Office requires Windows testing.

`get_default_service()` shares one owner **within a process**. Explicit `ConversionService()` instances
are independent owners. The Explorer adapter now provides a per-user owner lock, local mailbox and classic menu
registration; see EXPLORER.md. It forwards to the desktop's existing singleton. The CLI parser and headless adapter are now implemented in puryf/cli.py; see CLI.md.
Optional local stdio MCP and HTTP gateways now wrap the service; there is no system-wide daemon. Separate future processes must
forward work to a chosen service host to preserve one coordinated queue.

## Safety and cancellation

- Original atomic staging, no-overwrite defaults, filename reservations and dependency checks remain.
- The service protects source paths from every known job. A lock covers final destination checking
  and commit, so a newly submitted source cannot be overwritten during a competing commit.
- If a path becomes protected after conversion selected its destination, that commit fails safely
  rather than replacing the new source. Inspect the structured job error and choose another destination.
- Queued cancellation immediately marks the job cancelled. Running cancellation sets a per-job event;
  external commands are terminated, while an active Office call must return before cancellation completes.
- Unstarted inputs are marked Cancelled. Already committed outputs remain in the result list.
- PDF splitting prechecks its destinations and publishes each completed part, so outputs stay discoverable
  if cancellation or failure interrupts later parts. A whole batch is not a filesystem transaction.
- Progress, report-writing problems and partial successes are available through the same job contract.

## Current limits

Core jobs accept individual regular files. Folder expansion and safe ZIP extraction remain in the
desktop input adapter; shared input expansion is a later adapter task.

Jobs and event subscriptions live in memory. Existing desktop session recovery remains available, but
this is not a durable server-job database. Long-running hosts must plan history/event retention,
authentication, permitted folders and output retention in their later adapters.
This library does not start a network listener or expose arbitrary shell-command execution.
The existing Python-required installer is retained; standalone runtime bundling remains a later milestone.


## Explorer desktop adapter

`puryf/explorer.py` contains only standard-library handoff/election code. Public package exports
are lazy, so secondary processes never load Tk/converters. `desktop.App.accept_explorer` runs
on the Tk thread and submits fixed `ConversionOptions()` with origin `explorer`, or adds waiting
rows without creating a job. The owner retains the lock until its main loop and worker shutdown
finish. Pending rows recover to Queued after interrupted sessions. See EXPLORER.md for the
transport schema, delivery semantics, validation limits and installer lifecycle.


## CLI adapter and process coordination

`puryf.cli` and `PuryF_CLI.py` implement console commands without loading Tk. Flags and strict
version-1 request files normalize to one internal request, then use ConversionService for all work.
Folder expansion is adapter-side, deterministic, snapshotted before conversion, with symlink and
output-subtree exclusions. Explicit bad paths remain per-item job failures.

Each worker now acquires an OS file lease in the per-user Conversion directory before starting a
job. One CLI/desktop host may execute converters at a time; lease waits cancel promptly and the OS
releases the lease after owner death. COM init, use and cleanup remain on the existing worker thread.
The lease provides exclusion, not a global FIFO, shared registry, broker, or cross-host source index.
Do not overwrite destinations another host has queued as sources; prefer safe default output handling.
Desktop/Explorer still share a GUI window; CLI conversions use a separate headless job registry.
Use `puryf gui FILE...` to place waiting inputs in that GUI rather than starting a CLI conversion.
`doctor` only preflights capabilities/paths and never initializes Office.

`installer/path_setup.py` owns one user PATH entry and preserves raw value type/references and
unrelated entries. Deselecting or uninstalling removes only a recorded owned entry. Native registry,
console forwarding and actual Office behavior remain Windows validation tasks.


## Integration gateway

`access.py` validates server configuration, explicit folder policy and account tokens.
`gateway.py` owns a private managed workspace, a SQLite metadata/idempotency/usage store,
one ConversionService and independent maintenance/webhook workers. Uploaded documents are
opaque tenant-owned IDs; clients cannot supply hosted filesystem paths or output destinations.
Only public snapshots and HMAC request fingerprints are persisted, never passwords/raw requests.

`mcp_server.py` serves versioned newline-delimited JSON-RPC over local stdio; asynchronous tools
return job IDs and explicit status/results/cancel tools. `http_server.py` implements authenticated
loopback REST routes and bounded file transfers. Both adapters call the same gateway contract.
`webhooks.py` sends account-scoped administrator HTTPS presets with HMAC headers and no redirects.

Terminal core history is forgotten at retention expiry through ConversionService.forget, which
rebuilds its known source set. Completed public results/idempotency survive restart; interrupted
jobs fail without automatic repeated execution. A single OS data-directory lock prevents multiple
owners of a SQLite workspace. This is a single-host preview, not a durable distributed task queue.
Logical tenant ownership/private filesystem directories are not hostile-document OS sandboxes.
See MCP_API.md for contracts and HOSTING.md for the public production boundary.
