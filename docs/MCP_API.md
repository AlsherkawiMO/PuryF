# MCP and local API — 1.0.0

This release adds a local stdio MCP server, an optional loopback HTTP API, and a
hosted-workflow preview. None starts automatically. Desktop, Explorer and CLI
remain available. The server uses the existing conversion service and per-user
conversion lease; it does not require Tk for headless work.

## Setup

Copy a JSON example from `integration-configs/`, edit the paths, and keep it outside
the source tree when upgrading. Every data directory must be absolute, dedicated,
initially empty, and private to the server OS account. Do not point it at Documents
or another project. One integration host owns each data directory. Windows examples
contain YOUR_NAME placeholders; Linux/macOS users must replace them with native paths.

Input folders must already exist. Local/MCP inputs require absolute regular-file
paths beneath `read_roots`. Linked files/directories and Windows junctions are
rejected. Missing roots deny startup; there is no implicit access to your whole PC.
Converted PDFs are written under the configured data directory in unique job-owned
folders. Clients cannot select arbitrary output paths or enable overwrite.

Use the installed `puryf` command when its PATH component was selected, or use
`python -m puryf ...` / `Run_CLI.bat ...` from the source root. For a headless source
installation, install `requirements-server.txt` instead of desktop dependencies.
The Windows source installer still requires Tk because it includes the desktop.

## MCP: local stdio first

```bat
puryf mcp --config "C:\PuryF-config\mcp.json"
```

Set `mode` to `mcp`. No HTTP key or port is required: the client launches a local
child process, and folder permissions come from your administrator-edited config.
Use a dedicated data directory distinct from a running API's directory.

Example client configuration (adapt the outer `mcpServers` format to your MCP client):

```json
{
  "mcpServers": {
    "puryf": {
      "command": "C:/Users/YOUR_NAME/AppData/Local/Programs/PuryF/.venv/Scripts/python.exe",
      "args": O
        "C:/Users/YOUR_NAME/AppData/Local/Programs/PuryF/PuryF_CLI.py",
        "mcp", "--config", "C:/PuryF-config/mcp.json"
      ]
    }
  }
}
```

| Tool | Purpose |
| --- | --- |
| puryf_convert | Convert permitted local files; returns a background job ID |
| puryf_merge | Merge PDF inputs in order |
| puryf_split | Extract `pages` or split `every` N pages; one input |
| puryf_dependencies | Preflight selected permitted files |
| puryf_capabilities | Formats, readiness and configured limits |
| puryf_job_status | Poll progress, state, errors and output metadata |
| puryf_cancel | Request job cancellation |
| puryf_results | Verified absolute output PDF paths for completed jobs |

Submission tools return promptly. Poll status using the returned job ID; progress is
job progress, not an unsolicited notification after a completed MCP request. Cancel
jobs explicitly through `puryf_cancel`. Cancelling an already-completed MCP request
cannot undo a submitted job. An active synchronous Office call must return before
cancellation completes. Closing stdin cancels/cleans up jobs and shuts down the host.

Newline-delimited JSON-RPC stdout contains protocol messages only; diagnostics go to
stderr. Incoming messages are capped at 1 MiB; oversized messages terminate the stream.
Supported protocol eras:

- `2026-07-28`: `server/discover` and per-request protocol-version `_meta`; complete
  tool results include `resultType`. No initialization handshake is required.
- `2025-11-25`, `2025-06-18`, `2025-03-26`: initialize/initialized legacy handshake.

Unknown modern versions return `-32022` with supported versions. Unknown methods and
invalid tool names return JSON-RPC errors; tool execution failures use `isError`.
There are no advertised prompts/resources/subscriptions. Standard-stream request
cancellation is not a substitute for the explicit asynchronous job-cancel tool.
**Streamable HTTP MCP is intentionally deferred**; the REST API is not an MCP transport.

References: OMCP stdio transport](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/stdio.mdx),
OMCP schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.json).
Wire behavior has automated tests; connecting real third-party MCP clients is a remaining
compatibility check. No client settings are changed by the installer.

## Local HTTP API

Copy `local.example.json`, set `mode: local`, permitted roots and a private data folder.
Create a random token, then set its referenced environment variable in the terminal
that starts the server. Example using Command Prompt, without PowerShell:

```bat
py -3 -c "import secrets; print(secrets.token_urlsafe(32))"
set "PURYF_LOCAL_TOKEN=PASTE_THE_GENERATED_TOKEN_HERE"
puryf serve --config "C:\PuryF-config\local.json"
```

Use at least 32 characters; placeholder/empty keys refuse startup. One account is
allowed in local mode. HTTP authentication uses `Authorization: Bearer YOUR_TOKEN`.
Tokens are not accepted in query parameters. Your MCP client/HTTP caller may retain its own request traces; avoid sharing password-bearing traces. The server binds **127.0.0.1 only**;
there is no automatic firewall rule, LAN listener, system service or startup task.
Never put real keys in an example config or website source. Rotate a key by changing
its environment variable and restarting the server; use separate keys per customer
in hosted mode.

`curl.exe` example (CMD expands the environment variable):

```bat
curl.exe -H "Authorization: Bearer %PURYF_LOCAL_TOKEN%" http://127.0.0.1:8765/v1/capabilities
```

A local submission JSON body:

```json
{
  "operation": "convert",
  "inputs": O"C:/Users/YOUR_NAME/Documents/Conversion-inputs/notes.txt"],
  "options": {"compress_pdf": false}
}
```

Submit with `Content-Type: application/json` to `POST /v1/jobs`; response 202 contains
`job.id`. Supply an `Idempotency-Key` of 8–128 ASCII letters/digits/`._:-` when retrying
submission. Identical request/key/account replays the same job (200), including after
a restart. A different request with that key returns 409. Omit the header to submit a
new job. Key records expire with job retention, so reuse after expiry can create new work.

## Endpoint contract

Oopenapi.json](openapi.json) describes the routes; all `/v1` endpoints require a token.
JSON bodies are limited to 128 KiB. Files use a separate bounded binary upload.

| Method and path | Result |
| --- | --- |
| GET /v1/capabilities | Enabled formats, dependency readiness and global limits |
| POST /v1/dependencies | Preflight `{ "inputs": O...] }` |
| POST /v1/uploads?name=notes.txt | Hosted-only raw file body; returns upload ID (201) |
| POST /v1/jobs | Submit convert/merge/split job (202), or idempotent replay (200) |
| GET /v1/jobs/ID | Status, progress, per-input states, outputs, safe errors |
| GET /v1/jobs/ID/results | Same current job/result snapshot |
| POST /v1/jobs/ID/cancel | Body `{}`; request cancellation |
| GET /v1/jobs/ID/files/INDEX | Authenticated individual PDF, after job is terminal |
| GET /v1/jobs/ID/archive | Authenticated ZIP of available outputs |
| POST /v1/jobs/ID/links | Mint a temporary individual/ZIP link |
| GET /d/GRANT | Download with a signed expiring bearer grant; no API key required |

Submissions accept `operation`, `inputs`, optional `options`, `input_password`,
`output_password`, and `webhook_id`. Split additionally requires exactly one of
`pages: "1-3,7"` or `every: 5`. Merge/split accept PDF inputs only. Source passwords
apply to merge/split; output passwords enable AES protection. Passwords never enter
public snapshots or persisted raw requests. The idempotency fingerprint is HMAC-protected.
`options` uses ConversionOptions but prohibits output_folder, overwrite, password_pdf
and pdf_password. PDF-tool jobs reject conversion merge/compression/OCR flags. Hosted
OCR is disabled. All outputs are managed files, and sources remain protected.

Snapshots use public job IDs, input/output names and asset indices. They omit server
paths, raw converter logs, reports and detailed converter errors. MCP's results tool
can return local paths because it runs under the same local folder policy. Errors
include stable codes; use local administrative diagnostics for debugging sensitive files.

HTTP error classes: 400 invalid request, 401 bad/missing key, 403 folder/Host/Origin
restriction, 404 unknown or cross-account object, 409 idempotency/not-finished conflict,
410 expired job/file, 411 missing length, 413 body limit, 415 content type,
422 disabled route/bad document, 429 usage limit. Token authentication applies before
job lookup, and tenant checks apply to uploads, jobs, cancellation, downloads and link creation.

Uploads require a single Content-Length; chunked request bodies are rejected. The
server bounds concurrent connections and timeouts. Origin headers require an exact
`allowed_origins` match; defaults deny browser origins. Host headers must match the
loopback listener or configured `allowed_hosts`. These controls complement tokens,
not replace them. CORS does not bypass authentication. Responses are `no-store`.

## Limits, persistence and cleanup

Defaults: 20 inputs/job, 10 MiB/file, 4 active jobs/customer, 100 jobs/rolling 24 hours,
500 MiB of uploads/job files/customer, 120 authenticated requests/minute. Upload count
is also capped to jobs/day × max_files/day. Limits are per account and configurable.
PDF uploads cap unencrypted page counts at 1,000; encrypted PDFs are checked after
unlock for PDF-tool jobs. Images cap dimensions at 40 million pixels and 1,000 frames.
These are application limits, not a hostile-document sandbox or guaranteed CPU bound.

Job deadlines request cancellation after the configured interval (default 900 seconds).
The engine may need to return from an in-process/Office call first. Output storage is
checked at completion; quota-exceeding job outputs are removed and the job fails safely.
ZIP creation requires space for an additional output copy. Reports are private server
files and are swept separately; metadata/filesystem overhead also needs disk headroom.

SQLite stores ownership, public snapshots, request fingerprints, usage counters and
webhook delivery state. It does not persist passwords. Completed results and idempotency
survive restart. Interrupted/reserved jobs become `server_restarted` failures instead of
being automatically repeated. A transactional durable multi-worker queue is later work.

Retention defaults to 24 hours, configurable from 60 seconds to 7 days. Expired jobs,
outputs, ZIPs and unreferenced uploads are deleted automatically. Active jobs pin their
uploads until completion/cancellation. Crashed unregistered upload/work folders and old
reports are swept after retention. Usage counters retain 7 days of counts. Terminal
service jobs are forgotten to bound memory. SQLite backups/WAL/free pages may retain
deleted metadata; this is logical cleanup, not forensic secure erasure. The OS owner
must manage backups and storage-level retention. Do not modify managed directories
while the server is running.

## Completion webhooks

Only administrator-configured HTTPS presets can be selected, and each preset belongs
to one account. Add an object like `webhook.example.json` under config `webhooks`, set
the referenced signing-secret environment variable, and submit `webhook_id` with a job.
Client-supplied callback URLs are rejected. Preset URLs and their DNS/egress destinations
are administrator-trusted; use an outbound network allowlist when deploying.

Completion payload: `{ "event": "job.completed", "job": PUBLIC_SNAPSHOT }`.
Headers: `X-PuryF-Delivery` is the public job ID; `X-PuryF-Timestamp` is Unix seconds;
`X-PuryF-Signature` is `sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)`.
Verify before parsing, require a fresh timestamp (for example ±5 minutes), and deduplicate
delivery IDs in your receiving database. No API keys or automatic download grants are sent.
Fetch results using your key or deliberately mint a temporary link.

Delivery runs on its own bounded worker, with a five-second request timeout, no redirects,
and up to five attempts with exponential delays. State survives restart; in-flight
attempts are retried. Shutdown bounds its wait for a slow callback; an unfinished claimed delivery remains recoverable. Delivery is at least once, so receivers must tolerate duplicates.
External receiver availability and egress must be tested on the deployment network.

For public hosting, website integration and cost planning, see OHOSTING.md](HOSTING.md).
