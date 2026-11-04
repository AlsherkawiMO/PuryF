# Changelog

## V1 PDF Studio navigation fix

- Corrected the sidebar callback to read selected queue items as (row, item) pairs.
- Clicking PDF Studio opens it immediately, including with an empty queue.
- Single and multiple selected PDFs load automatically; Add PDFs remains inside Studio.
- Added regressions that invoke the actual sidebar button.


## 1.0.0 — 2026-11-04

- PDF Studio: preview, thumbnails, page arrangement, bookmarks, metadata, stamps,
  text and image export, target-size compression and a numbered course-pack workflow.
- Shared queue pause/resume, presets, batch naming, folder preservation, history,
  repeat jobs, preflight, byte-duplicate review, notifications and redacted diagnostics.
- Watch folders, interval schedules, background control, Python SDK and trusted converter extensions.
- Arabic primary interface with mirrored layout and Arabic text/OCR review.
- Native Windows standalone build pipeline, portable packaging, smoke test and clean-PC checklist.
- Complete tutorials consolidated in README.md.

Release status: source preview. Windows standalone binaries and clean-PC validation are pending.
Hosted API remains a developer preview. Existing GUI, CLI, Explorer, MCP and APIs are retained.

# Changelog

## 0.5.0-alpha.1 — 2026-11-04

- Local stdio MCP with modern discovery/metadata and legacy initialization support.
- Conversion/PDF/dependency/capability/status/results/cancel tools under configured folder access.
- Optional bearer-token loopback API and tenant-scoped hosted-upload preview.
- Persistent job ownership, public results, HMAC idempotency fingerprints and usage limits.
- Single/bulk uploads, individual/ZIP downloads and signed expiring download grants.
- Account-owned HTTPS webhook presets, HMAC signing, durable retry/claim state and bounded dispatcher.
- Automatic retention cleanup, active input pinning, output quotas and terminal core history removal.
- Hosted Office and unsupported server routes rejected; production isolation limits documented.
- OpenAPI, browser/backend examples, staging container references and cost/capacity planning.

## 0.4.0-alpha.1 — 2026-11-04

- Added headless gui/convert/merge/split/doctor/request terminal entry points.
- File and mixed batches, deterministic shallow/recursive folder scans, duplicate collapse,
  output-subtree exclusion and versioned JSON request files for large lists.
- Human progress, structured JSON results/errors, meaningful exit codes and Ctrl+C cancellation.
- Password environment references for protected outputs and encrypted merge/split sources.
- Added a per-user conversion lease across CLI/desktop hosts, retaining one Office worker per host.
- Optional user PATH command, remembered component choice and ownership-aware PATH cleanup.
- Added subprocess CLI, signal, cross-process lease and PATH-preservation tests.

## 0.3.0-alpha.1 — 2026-11-04

- Added classic Explorer Convert to PDF and Add to queue actions for mixed file selections.
- Added a lightweight per-user desktop owner lock and atomic local request mailbox.
- Reuse one window; accept additional batches while the shared Office worker runs.
- Queue-only additions stay waiting; Explorer conversions use explicit safe defaults.
- Coalesce adjacent handoffs and avoid resubmitting active/pending source paths.
- Optional per-user installer registration, remembered upgrade choice, owner-scoped
  registry cleanup and transport-data cleanup on uninstall.
- Added real multi-process handoff and desktop integration tests; documented legacy limits.

## 0.2.0-alpha.1 — 2026-11-04

- Extracted a headless conversion engine and PDF tools from the desktop.
- Added immutable validated options, structured jobs, events, results and cancellation.
- One coordinated FIFO worker owns all Office calls and cleanup.
- Desktop conversions and manual PDF tools now use the shared job service.
- Added final-commit source protection across jobs and cancellation checks.
- Added headless, concurrency, lifecycle and GUI integration regression tests.
- Updated the installer to include the shared package.


## 0.1.0-beta.1 — 2026-11-03

- Dark theme becomes the first-launch and prototype-upgrade default; subsequent theme choices are preserved.
- Orange origami-cat identity, light/dark logo assets and Windows icon.
- Convert, PDF tools and Dependencies pages, with collapsible advanced settings.
- Conversion actions stay visible while the main content scrolls.
- Existing conversion engine and original feature entry points preserved.
- Queue-selection PDF merging, private-environment launcher and per-user source installer.
- MIT license, contributor guide, README, actual-app screenshots and regression tests.

Known limits: Windows installer execution, Office automation, physical Windows input and DPI scaling
need target-device verification. CAD conversion is unavailable. Optional converters require separate setup.
