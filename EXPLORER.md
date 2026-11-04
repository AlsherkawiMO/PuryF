# Windows Explorer integration — 1.0.0

Choose **Explorer right-click actions (classic menu)** in the installer's Components
screen. It is off for new installations and remembered on upgrades. No administrator
access is needed. On Windows 11 use **Show more options** to reach the classic menu;
a native modern Windows 11 extension is a later milestone.

| Action | Behavior |
| --- | --- |
| Convert to PDF with PuryF | Open/reuse the desktop window and submit the selected supported files immediately. |
| Add to PuryF queue | Open/reuse the window and add files as Queued; do not submit a job. Press Start when ready. |
| Open PuryF from Start menu | Bring the existing window forward, or create it if none is running. Windows may restrict foreground focus. |

Select one file or mixed formats. The two actions appear for all files so mixed
selections share the same verbs. Unsupported/missing files, Office temporary files,
folders, ZIPs, CAD and `.url` shortcuts are skipped with activity-log messages.
Use the desktop's folder/ZIP import for those supported ingestion operations.
Unavailable conversion dependencies become per-file job errors; other valid inputs continue.

## Explorer defaults

These settings do not inherit the last desktop output folder, password or other toggles.
Queue-only files use the GUI settings when you later press Start.

| Setting | Explorer conversion value |
| --- | --- |
| Destination | Beside each source file |
| Name | Source stem + `.pdf`; PDF inputs use `_processed.pdf`; existing collision/source guards apply |
| Existing output | Skip with a visible item error; never overwrite |
| Merge / compression / OCR / password | Off |
| Images | Original size |
| PowerPoint | Full-page slides; Remove date |
| Excel fit-to-width | Off |
| External command timeout | 900 seconds |

No dialog is required to submit a batch. Results, dependency errors, progress and
reports appear in the existing desktop UI. Stop cancels the active job; queued jobs
retain the shared service's normal behavior. Closing cancels all submitted jobs.
Files added with the queue action remain waiting even after earlier jobs finish.
A queued source explicitly passed to Convert is submitted; sources already in active
or pending jobs are not submitted again. Completed sources may be explicitly retried,
subject to the no-overwrite default. Duplicate paths within one incoming batch collapse.

## One window and additional batches

`PuryF.py` is the entry point for all shortcuts and installed context-menu commands.
A short launcher publishes an atomic JSON request under
`%LOCALAPPDATA%\PuryF\Explorer\pending`, then tries a per-user file lock. The winning
process creates the desktop; other launchers wait for acknowledgement and exit.
The lock is released by the OS if its owner crashes. A forwarding process can become
the new owner if the previous window closes before accepting its request.

The desktop polls on its Tk thread. Adjacent requests with the same action are combined
into bounded batches, in publication order; Explorer's original selection order is not
guaranteed. This handles legacy Explorer's separate per-file launches without opening
separate windows. Different clicks can become one job, or a large selection can become
several jobs, depending on arrival times. All jobs use the same FIFO/Office worker.
Incoming batches are accepted while conversion is running; queue-only rows never start
automatically. The publisher imports neither Tk nor conversion libraries.

The mailbox is local IPC for the current OS user. It has no network listener or remote
credentials and does not support other users/machines. Requests accept only a version,
action and absolute paths; settings and executable commands are not accepted. Requests
are limited to 1 MiB and 2,000 paths; each tick reads at most 100 request files. Filesystem
permissions inherit the user's local app-data directory. This trusts processes already
running as that user, like the desktop application itself.

Acknowledgement happens after queueing/submission. Unacknowledged requests survive a
crash/closing window and are retried on the next launch. Delivery is at least once,
not a durable exactly-once job system; a crash between submission and acknowledgement
can retry a request. Source/no-overwrite guards remain in force. Malformed requests are
rejected and removed with a log entry. A handoff that cannot be accepted in 60 seconds
shows an error and leaves the request available for the next launch. A `.tmp` file left
by an interrupted publisher is never processed.

## Registration, upgrades and removal

The installer owns only these two per-user keys:

- `HKCU\Software\Classes\*\shell\PuryF.Convert`
- `HKCU\Software\Classes\*\shell\PuryF.Queue`

Both set `MultiSelectModel=Player` and a quoted direct `pythonw.exe` command with
`--explorer-convert -- "%1"` or `--explorer-queue -- "%1"`. No `cmd.exe`, PowerShell,
file association changes or default-open changes are involved. `--` protects paths
beginning with option-like names. Every file gets its own lossless JSON handoff, avoiding
an aggregate command-line length limit.

Upgrades retain the chosen component, refresh commands for the installed location,
and remove this installation's old verbs if the component is deselected. Uninstall
checks each verb's `PuryFOwner` before deleting it and sends an association-change
notification. It also removes transport-owned pending requests, temporary request files
and the lock file; source documents, outputs, reports and saved GUI session are kept.
Use one installed location per user; upgrade in place. The desktop and cross-process conversion locks are checked
before setup/uninstall. Close legacy releases too: versions before 0.3 do not hold that
lock and cannot be detected by it.

Microsoft documents a **100-item legacy Player limit**. Above that, these verbs may not
appear. Use desktop import for larger batches. We do not change Explorer's global
selection limits. A native selection-aware COM extension can be considered with the
modern menu work:
[verb selection model](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-employ-the-verb-selection-model),
[verb command quoting](https://learn.microsoft.com/en-us/windows/win32/shell/fa-verbs).

## Validation status

Automated checks exercise real multi-process launch handoffs, owner death/recovery,
Unicode/space/shell-character paths, mixed real text/image conversions, queue-only
behavior, busy-worker arrivals, fixed defaults, duplicate handling and dependency errors.
The installer is compiled with NSIS. These tests run on Linux with Tk 8.6 and Tk 9.
Actual Explorer invocation, Windows `msvcrt` locks, registry writes, installation,
upgrade/deselection and uninstall must still be validated on Windows using
[WINDOWS_CHECKLIST.txt](WINDOWS_CHECKLIST.txt). Office is tested with a lifecycle mock,
not an installed Microsoft Office application. This is a source preview; Windows release validation is pending.

CLI commands are now available; see CLI.md. Conversion workers also acquire a per-user
lease, so concurrent headless CLI jobs wait while a desktop/Explorer conversion runs.
