# PuryF command line — 1.0.0

During Windows setup, optionally select **Terminal puryf command on user PATH**.
Open a new Command Prompt or terminal afterwards. The component is off for new installs;
your selection is remembered on upgrades. The desktop and Explorer remain optional entry points.

```bat
puryf --help
puryf --version
puryf gui
puryf gui "C:\Training\notes.txt"
puryf gui --convert "C:\Training\slide.pptx"
puryf convert "C:\Training\notes.txt" "C:\Training\diagram.png"
puryf convert "C:\Training" --recursive --output-dir "C:\PDF output"
puryf merge first.pdf second.pdf --output combined.pdf
puryf split combined.pdf --pages "1-3,7" --output selected.pdf
puryf split combined.pdf --every 5 --output-dir parts
puryf doctor
puryf doctor slides.pptx
puryf doctor --all --json
puryf convert notes.txt --json
puryf request batch.json --json
```

Without the PATH component, use `Run_CLI.bat` in the extracted source folder, or
`python PuryF_CLI.py ...` / `python -m puryf ...` with the dependencies installed.
`Run_CLI.bat` uses the private `.venv` if present, otherwise the Python launcher.
`python -m puryf` must run from the source root (or have that root on PYTHONPATH).
`PuryF.py` remains the desktop/Explorer launcher; `PuryF_CLI.py` is the console launcher.
The installer requires Python 3.10+ with Tk/pip/venv and internet for dependencies.

A runnable source example is included: `puryf request examples/convert.request.json --json`.
It converts `examples/notes.txt` into `examples/pdf-output` without Office.

## Inputs, outputs and safety

`convert` accepts individual files and folders, and mixes them in one job. A folder
scans its immediate files by default; `--recursive` scans subfolders too. Folder results
are sorted by name and duplicate resolved paths collapse. Directory symlinks below a
selected root are not followed. A nested output folder is excluded from the scan. The
scan is snapshotted before conversion, so new PDFs cannot re-enter that running job.

Folder scans skip unsupported extensions, ZIP, CAD, `.url` shortcuts and Office `~$`
files. The JSON scan result counts ignored files and records directory traversal errors.
Explicit unsupported/missing filenames become per-item errors; valid batch items continue.
An empty scan is a usage error. Existing PDFs in an input folder are included, so use a
separate output folder for repeatable source-folder conversion. Shell wildcard expansion
is not implemented; pass files, folders or a request file instead.

Outputs save beside each input unless `--output-dir` is given. PDF inputs save as
`name_processed.pdf` when writing beside the source. Names/format collisions and known
job-source paths use the existing engine safeguards. Existing outputs skip by default;
`--overwrite` permits replacing output files, while registered job sources remain protected.
Folder structure is not reproduced beneath the output folder; the existing collision
naming rules keep same-stem inputs distinct within the job.

Merge preserves the supplied PDF order. Page ranges are 1-based inclusive, e.g. `1-3,7`;
interval splitting uses `--every N` and names outputs with their page ranges. Sources
are not edited. Encrypted PDF inputs for merge/split can use `--input-password-env NAME`
(one password for the selected inputs). Conversion of already encrypted PDFs does not
prompt for a source password; use an unlocked source or the PDF-tool commands instead.

## Options

`convert` supports:

- `-o/--output-dir FOLDER`, `-r/--recursive`, `--overwrite`.
- `--merge` to also create a merged PDF, `--compress`, `--ocr`, `--ocr-language eng`.
- `--image-paper "Original size"|A4|Letter`, `--excel-fit-width`.
- `--ppt-layout NAME`, `--ppt-date-mode NAME`, `--timeout SECONDS` (external commands, default 900).
- `--password-env NAME` to encrypt outputs using a nonempty environment variable.

PowerPoint layout names: `Full-page slides`, `1 slide per page handout`,
`2 slides per page handout`, `3 slides per page handout`, `4 slides per page handout`,
`6 slides per page handout`, `9 slides per page handout`, `Speaker notes under each slide`.
Date modes: `Remove date`, `Keep existing date`, `Add today's date`.

Merge/split support `--overwrite`, `--password-env NAME` and `--input-password-env NAME`.
They do not accept conversion post-processing flags. No raw password command-line option
is provided. Password values stay out of JSON results and job snapshots. Request files
also refer to environment variable names rather than storing passwords. Set/clear those
variables using your shell's normal environment tools; inherited variables are visible
to processes with the same user privileges.

`--json` and `--quiet` can appear before or after the subcommand. JSON prints one
versioned document on stdout and suppresses normal progress. Human progress is printed
as lines on stderr; result paths and the summary are printed on stdout. Quiet suppresses
progress and human summaries; validation errors still go to stderr. Help/version remain
plain text even when `--json` is supplied. Paths needing shell quoting must be quoted;
for unusual characters or very long lists, use a request file.

## JSON request files

A request avoids Windows aggregate command-line length limits. Files are UTF-8 (BOM
accepted), limited to 16 MiB and 100,000 explicit input paths. Paths, including output
folders, are relative to the request file's own directory unless absolute.
There is no arbitrary command execution, nested request inclusion or GUI request mode.
Unknown fields, invalid option names/types, raw password fields and unsupported versions
are rejected before submission.

```json
{
  "version": 1,
  "command": "convert",
  "inputs": ["course notes.txt", "slides.pptx", "images"],
  "recursive": true,
  "options": {
    "output_folder": "pdf-output",
    "overwrite": false,
    "image_paper": "A4",
    "merge_pdf": false,
    "compress_pdf": false,
    "ocr_pdf": false
  }
}
```

`options` accepts the shared `ConversionOptions` fields except `password_pdf` and
`pdf_password`; use top-level `password_env` instead. In addition to base fields
`version`, `command`, `inputs`, each command accepts:

| Command | Extra request fields |
| --- | --- |
| convert | recursive, options, password_env |
| merge | output, options, password_env, input_password_env |
| split | output + pages **or** output_dir + every; options, password_env, input_password_env |
| doctor | recursive, all |

A merge request needs an `output` filename. A split request needs one input and exactly
one output mode. `options.output_folder`, merge/compress/OCR flags are not accepted by
merge/split. Partial or invalid filesystem scans are reported; complete conversions with
scan errors still return a partial-success code.

## Results and exit codes

JSON has `schema_version: 1`, `command`, and `exit_code`. Conversion/PDF-tool results
contain the existing `result` job snapshot plus `scan`: job ID, accepted public options,
progress, per-input status/output/error, output list, logs, cancellation and report path.
Doctor has a `doctor` report. Validation/runtime failures contain an `error` object.
GUI reports `launch_requested` and a launcher PID, not a guarantee of display availability.

| Code | Meaning |
| --- | --- |
| 0 | All requested work succeeded; doctor ready; or GUI launch requested |
| 1 | Conversion/PDF/I/O failure with no completed outputs |
| 2 | Invalid syntax, request, options, split mode, or no supported inputs |
| 3 | Doctor found missing requirements / invalid selected sources; or all job failures are dependency errors |
| 4 | Partial work: some outputs succeeded but files failed/skipped, or directory scan errors occurred |
| 5 | All conversion inputs skipped because their outputs already exist |
| 70 | Unexpected internal failure |
| 130 | Interrupted/cancelled |

The underlying job can say `succeeded` when some items were safely skipped; the CLI
still returns 4 if other items succeeded, or 5 when everything skipped. Always inspect
per-item results when automation needs precise handling. Interval splits can retain
completed parts after a later failure or cancellation.

Press Ctrl+C to request cancellation and wait for cleanup. External commands cancel;
an active synchronous Office call must return first. A cancelled JSON command still
returns its job snapshot where available. Force-killing a process cannot guarantee
cleanup of its external Office application.

## Diagnostics and coordination

`doctor` checks core modules and reports requirements by supported format. Optional
missing converters do not fail a basic doctor run. Selected inputs are preflighted;
`--all` requires every implemented format capability. CAD/URL and ZIP conversion are
excluded. Office diagnostics check registration and pywin32, not whether actual documents
render successfully. GUI diagnostics check module availability, not display connectivity.
No Office instance is launched by doctor.

Headless CLI commands do not import Tk and do not open a desktop window. Each CLI
invocation has its own in-memory job registry/FIFO, using the same `ConversionService`
and one Office-owning worker. GUI/Explorer share the existing single desktop window.
A shared per-user conversion lease under `%LOCALAPPDATA%\PuryF\Conversion` now serializes
whole jobs across these processes: only one host converts at a time. Waiting is
cancellable; OS locks release after a process exits/crashes. This is mutual exclusion,
not a global FIFO/job broker or a shared history database. `puryf gui` hands files to
the GUI queue; ordinary `convert` results stay in the invoking terminal. Source guards
cover each host's registered jobs; do not opt into overwrite when another process has
queued that destination as an input. Versions before 0.4 do not honor the new lease.

## PATH component and lifecycle

The optional command is a small `bin\puryf.cmd` wrapper around the installed private
Python console interpreter. Only the dedicated `bin` directory is added to **user**
PATH. Raw registry strings, expandable references, value types, delimiters and unrelated
entries are preserved. A pre-existing entry is not claimed or removed. Upgrades retain
the component choice; deselecting it removes PuryF's owned entry and wrapper. Uninstall
removes only its owned entry and leaves other applications' PATH entries intact.

The helper writes `HKCU\Environment` and broadcasts the environment-change notification.
It does not run PowerShell or `setx`. Open a new terminal; an already-running terminal
or terminal host may need to be restarted before child shells inherit the new PATH.
References: [WM_SETTINGCHANGE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-settingchange),
[setx limitations](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/setx).

Native Windows command forwarding, Ctrl+C, PATH/registry notifications, upgrade and
uninstall still require target-PC validation. The installer is unsigned and compiled,
not executed on Windows in this development environment. Full standalone bundling,
Stdio MCP and optional HTTP gateways are now included; see MCP_API.md and HOSTING.md.

## Long-running integration commands

`puryf mcp --config FILE` starts stdio MCP; `puryf serve --config FILE` starts the loopback HTTP API.
Omit `--json`: these commands own their transport output. Neither starts automatically. Read
MCP_API.md before selecting folders/keys; hosted deployment limits and costs are in HOSTING.md.
