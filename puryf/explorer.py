# SPDX-License-Identifier: MIT
"""Per-user launch mailbox and process lock. No listener or network port."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import time
import uuid

MAX_REQUEST_BYTES = 1024 * 1024
MAX_PATHS = 2000

def runtime_dir():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share'))
    return base / 'PuryF' / 'Explorer'

class InstanceLock:
    """OS-released lock shared by Start menu, Explorer and source launches."""
    def __init__(self, directory):
        self.path = Path(directory) / 'instance.lock'
        self.file = None

    def acquire(self):
        if self.file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.file = stream
        return True

    def close(self):
        if self.file is not None:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None

def validate_request(data):
    if not isinstance(data, dict) or set(data) != {'version', 'action', 'paths'}:
        raise ValueError('Invalid Explorer request fields')
    if type(data['version']) is not int or data['version'] != 1 or data['action'] not in ('show', 'convert', 'queue'):
        raise ValueError('Unsupported Explorer request')
    paths = data['paths']
    if not isinstance(paths, list) or len(paths) > MAX_PATHS:
        raise ValueError('Too many Explorer paths')
    if any(not isinstance(p, str) or not p or '\0' in p or not Path(p).is_absolute() for p in paths):
        raise ValueError('Explorer paths must be absolute file paths')
    if (data['action'] == 'show') != (not paths):
        raise ValueError('A conversion or queue request needs files')
    return data

class Inbox:
    def __init__(self, directory=None):
        self.root = Path(directory) if directory is not None else runtime_dir()
        self.pending = self.root / 'pending'
        self.pending.mkdir(parents=True, exist_ok=True)

    def publish(self, action, paths=()):
        data = validate_request({'version': 1, 'action': action,
                                 'paths': [str(Path(p).resolve()) for p in paths]})
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError('Explorer batch is too large')
        stem = f'{time.time_ns():020d}-{uuid.uuid4().hex}'
        temporary = self.pending / (stem + '.tmp')
        target = self.pending / (stem + '.json')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def drain(self, handler, log):
        """Bounded UI work. Acknowledge after handler returns; retry after crash.

        Delivery is at least once: a crash after submission but before ack can
        produce a second safe PDF. Unacknowledged requests survive owner exit.
        """
        ready = []
        for path in sorted(self.pending.glob('*.json'))[:100]:
            try:
                if path.is_symlink() or path.stat().st_size > MAX_REQUEST_BYTES:
                    raise ValueError('Invalid Explorer request file')
                data = validate_request(json.loads(path.read_text(encoding='utf-8')))
            except (ValueError, OSError) as error:
                log(f'Explorer request rejected: {error}')
                path.unlink(missing_ok=True)
                continue
            ready.append((path, data))
        # Legacy Explorer can launch one process per selected file. Combine
        # adjacent actions into bounded batches, preserving queue/convert order.
        groups = []
        for path, data in ready:
            if (groups and groups[-1][0]['action'] == data['action']
                    and len(groups[-1][0]['paths']) + len(data['paths']) <= MAX_PATHS):
                groups[-1][0]['paths'].extend(data['paths'])
                groups[-1][1].append(path)
            else:
                groups.append((data, [path]))
        for data, files in groups:
            try:
                handler(data)
            except Exception as error:
                log(f'Explorer batch deferred: {error}')
                continue
            for path in files:
                path.unlink(missing_ok=True)

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='PuryF desktop and Explorer handoff')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--explorer-convert', action='store_true')
    group.add_argument('--explorer-queue', action='store_true')
    parser.add_argument('paths', nargs='*')
    args = parser.parse_args(argv)
    action = 'convert' if args.explorer_convert else 'queue' if args.explorer_queue else 'show'
    if (action == 'show') != (not args.paths):
        parser.error('Use --explorer-convert or --explorer-queue followed by file paths')
    return action, args.paths

def launch(argv=None):
    action, paths = parse_args(argv)
    inbox = Inbox()
    request = inbox.publish(action, paths)
    lock = InstanceLock(inbox.root)
    try:
        deadline = time.monotonic() + 60
        while True:
            if not request.exists():
                return 0
            if lock.acquire():
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('PuryF did not accept the batch within 60 seconds. It remains queued; reopen PuryF to retry.')
            time.sleep(0.1)
        from .desktop import App
        app = App()
        app.attach_explorer(inbox)
        app.mainloop()
        return 0
    finally:
        lock.close()
