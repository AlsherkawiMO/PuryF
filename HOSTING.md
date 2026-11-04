# Hosted API and website plan — 1.0.0

The upload-to-download workflow is implemented and tested on a loopback server. This
is a **single-host developer preview**, not a public multi-tenant production service.
No hosting, domain, storage account or paid resource has been created.

## Implemented now

- Single-file binary uploads and multi-file selection/upload followed by one bulk job.
- Background conversion/merge/split, public job IDs and polling progress.
- Individual PDFs, ZIP downloads and expiring signed download grants.
- Administrator-owned customer API keys, logical tenant ownership and quotas.
- Atomic idempotency reservations, persistent completed results and restart failure handling.
- Automatic upload/output/ZIP cleanup; active-job input preservation.
- Signed completion webhooks with durable retry state and account-scoped presets.
- Conservative server-side format validation and explicit Office rejection.
- A browser integration demo, Python backend/automation client, OpenAPI reference,
  configuration templates and reference container files.

## Run the hosted workflow locally

Copy `integration-configs/hosted.example.json`; edit `data_dir` to an absolute private
empty directory on your machine. Windows users must replace `/var/lib/puryf/data` with
a native path. Set the account's environment variable to a generated 32+ character key.
For a local demo, keep allowed origin `http://localhost:8080`. Start:

```bat
puryf serve --config "C:\PuryF-config\hosted-preview.json"
```

In another terminal, from the extracted source root:

```bat
py -3 -m http.server 8080 --bind 127.0.0.1 --directory website
```

Open `http://localhost:8080/`. Enter `http://127.0.0.1:8765` and your own
customer token, select one or several files, and convert. The page shows per-file
upload progress, job progress, cancellation, individual downloads, a ZIP and a
five-minute ZIP link. It keeps the key only in page memory and loads no third-party
scripts. Serve only this website folder; keep real configs, environment secrets and managed data outside the static file root. It is a developer demo, not a customer identity/login system.

`website/python_client.py` shows backend/automation integration. Set
`PURYF_CUSTOMER_TOKEN` and optional `PURYF_API_BASE`; then run:

```bat
py -3 website\python_client.py "C:\PDF-downloads" "C:\Training\notes.txt"
```

In hosted mode, `inputs` contains upload IDs, never server filesystem paths. Upload
files one at a time with `POST /v1/uploads?name=...` and a raw binary body, then submit
all IDs as one job. This avoids multipart parsing and aggregate command-line limits.
A partially failed bulk upload leaves its successful uploads available until retention;
it is not an atomic multi-file upload transaction.

## Office and route policy

Hosted allowlist: UTF-8 TXT/Markdown, common raster images, and PDFs. Content is parsed
and checked in addition to filename extension. CAD/URL/ZIP, HTML/SVG, ebooks, audio/video,
OCR and Office-dependent routes are rejected on this server. No fallback claims to have
rendered an Office document as text. Hosted `allow_office: true` is refused at startup.
Local MCP/API Office routes require explicit administrator opt-in and matching installed
Office/pywin32; they may still need interaction in the user's desktop session.

Microsoft advises against unattended server-side desktop Office automation because of
support/reliability problems. A future hosted Office backend must use a server-suitable
renderer or licensed service and pass DOCX/XLSX/PPTX fidelity tests: fonts, Arabic, page
breaks, print areas, slide notes, charts and embedded objects. Do not enable the existing
COM path in a web-service account. Source:
[Microsoft server-side Office considerations](https://support.microsoft.com/en-gb/visio/considerations-for-server-side-automation-of-office).

## Deployment boundary and next production work

The preview uses Python's standard-library HTTP server and in-process converters.
Python does not recommend `http.server` for production:
[official documentation](https://docs.python.org/3.12/library/http.server.html).
A TLS proxy alone does not turn this into a hardened public document-processing service.
Filesystem/account checks provide logical tenant segregation, not separate OS sandboxes.
Parser CPU/memory limits and cooperative cancellation do not contain arbitrary hostile files.

Before exposing unrestricted customer uploads, implement and validate:

1. A production HTTP frontend (ASGI/WSGI) with strict body/concurrency/time limits and
   a reverse proxy providing TLS, request limits and private upstream access.
2. A durable queue and per-job isolated worker/container with memory/CPU/disk/pid/time
   limits, no host mounts, no network egress, and a restricted service account.
   Keep webhook egress in a separate allowlisted dispatcher.
3. Real customer authentication/session handling, key provisioning/rotation/revocation,
   billing/admin workflow and an audited authorization boundary. Never ship one shared
   privileged key in public JavaScript. A website backend should map its authenticated
   customer to that customer's key/job ownership, without accepting spoofable owner IDs.
4. Object storage with tenant prefixes, private buckets, bounded signed URLs, lifecycle
   deletion, backups and retention policy; a transactional database for horizontal hosts.
5. Malware/parser abuse tests, dependency patching, load/fault tests and independent
   authorization testing. Validate physical deletion and capacity alerts.

Until then, run with trusted users/documents on a private machine or controlled staging
network. Current binding stays on 127.0.0.1. A user's API key is not an OS sandbox.
Modern Streamable HTTP MCP, resumable uploads, global multi-host FIFO and automatic
recovery/retry of unfinished conversion jobs remain later milestones.

## Reference container files

`deployment/Dockerfile` and `compose.example.yaml` are **unbuilt reference templates**
for Linux staging. Copy a real server config to `deployment/server.json` and create a
private `deployment/server.env` with only required key/signing variables. Do not commit
that file. Prepare `deployment/data` for UID/GID 10001. The container uses a read-only
root, a writable private data volume and bounded temporary storage. Its sample resource
budget is 2 CPUs, 4 GiB RAM and 64 PIDs; benchmark before choosing capacity.

The compose template uses Linux host networking so the API remains loopback-only behind
a host proxy. It is not a portable Windows/macOS Compose deployment. The resource limits
bound the whole server, not each customer/job; a worker-per-job sandbox is still needed.
Pin a tested base-image digest and dependency lock before deployment. This release does
not claim a successful Docker build or public TLS deployment.

Disable/redact reverse-proxy access logs for `/d/` bearer-grant paths, keep keys out of
logs, and use the application's no-store responses. Signed links can be used by anyone
holding them until expiry; expose that sharing choice intentionally. Account removal or
signing-key rotation revokes access, but deleting a downloaded copy is outside the server.

## Hosting/storage/operating-cost model

Start with your existing computer for local MCP/API: the software needs no paid API or
cloud subscription. Electricity, connectivity and optional Office licensing remain your
own costs. A public hosted service has resource/maintenance costs; this plan assumes no
unlimited free tier.

Estimate with measured values:

- CPU hours/month = jobs × mean processing seconds / 3,600.
- Average retained GB = daily jobs × mean (upload + outputs + requested ZIP) GB × retention days.
- Download GB/month = jobs × mean downloaded output GB × download/retry count.
- Peak disk = retained data + active job scratch + ZIP copies + logs/DB/backups + safety headroom.
- Monthly total = compute + storage + egress + backups + domain/TLS operations + monitoring
  + renderer licensing + maintenance time. Never count free transfer/storage allowances twice.

Illustrative sizing assumptions (not measured performance or live provider quotes):

| Scenario | Jobs/month | Mean processing | Input + output/job | Retention | CPU hours | Retained originals/results |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Small pilot | 1,000 | 5 s | 2 MB + 3 MB | 1 day | 1.39 | about 0.17 GB |
| Growing pilot | 10,000 | 10 s | 5 MB + 5 MB | 2 days | 27.78 | about 6.67 GB |

Using one output download/job gives about 3 GB and 50 GB/month respectively, before
ZIPs/retries. If every job also gets a ZIP, retained output bytes and download traffic
increase accordingly. Queues need peak-hour capacity, not just average CPU. OCR/video
would change these assumptions substantially and are not enabled here.

An example planning envelope might reserve USD 20–40 for compute, USD 5–10 for storage
and backups, USD 0–10 for egress, and USD 1–2 monthly equivalent for domain operations:
USD 26–62/month before labor/tax/licensing. These are budget placeholders, not prices,
provider recommendations or a commitment to spend. Obtain current quotes after measuring
real file sizes, conversion times, concurrency and transfer volume. No paid service has
been provisioned as part of this work.
