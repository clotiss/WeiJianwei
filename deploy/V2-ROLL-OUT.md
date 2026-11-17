# Policy V2 review and rollout

This runbook describes a staged rollout. Nothing here changes production by itself.

## Local checks

From `backend/`, install the pinned V2 dependencies, then run:

```sh
python -m playwright install firefox
python -m pytest -q
python -m compileall -q policy_v2 tests
python -m policy_v2.cli sources
```

From the repository root, run:

```sh
node --check miniprogram/utils/api.js
node --check miniprogram/app.js
node miniprogram/tests/api-v2.test.js
node miniprogram/tests/index-resilience.test.js
PYTHONPATH=backend python scripts/probe_sources.py --pages 2
```

The Firefox regression uses a local HTTP fixture, including a 412-to-200 navigation,
session cookies across list/detail requests, delayed rendering, and Retry-After.
The live probe can be bounded with repeated `--source` flags and `--pages 1|2|3`.
Install browser OS dependencies in a Linux staging image with Playwright's documented
`install --with-deps firefox` command before starting the worker.

## Staging order

1. Create a private staging database and object bucket. Inject credentials through the deployment secret store; never commit `.env` or keys.
2. Install V2 dependencies and the matching browser with `pip install -r requirements-v2.txt` and `python -m playwright install firefox`. Start `uvicorn policy_v2.app:app` from `backend/` on a private port. Route `/api/v2/` through Nginx after health checks. The API imports and creates the V2 schema, but it does not start the collector.
3. Run one `python -m policy_v2.cli worker` service. Schedule `python -m policy_v2.cli discover` every 6 hours. Keep all sources disabled until their individual trial is reviewed.
4. Verify private object writes, hash checks, attachment extraction, failure retry, task recovery, and backup restoration in staging.
5. Migrate a copy of the legacy SQLite database with `python -m policy_v2.cli migrate /path/to/legacy.db`. Compare totals and ID mappings. Legacy rows have no fabricated raw snapshot. Global legacy favorites have no account identity and need a product decision before they can be assigned to user accounts.
6. Validate source adapters on a small, manually reviewed sample. See `evidence/sources/manifest.json` for timestamped live results and transient failures. On 2026-11-17, NHC's two columns, first two pages and sample details succeeded with a shared Firefox context. NHC HTML now uses Firefox directly; waits require both document readiness and valid content, and record initial/final HTTP status separately. Jiangsu's two columns and sample details succeeded, with cross-domain NHC reposts filtered. Guangdong's first two pages and sample details succeeded. Hunan's default TLS negotiation failed with `BAD_ECPOINT` on both the developer machine and Tencent Cloud Ubuntu. A host-specific P-256 context restored verified HTTPS access; CA and hostname validation remain enabled. Hunan's table rows, actual pagination script and `#j-show-body` content parse successfully, but later local and Tencent Cloud probes still encountered intermittent handshake/read timeouts and TLS EOF errors. Keep sources paused until staging observations establish acceptable stability. Do not weaken TLS or automate challenge solving.
7. Test the mini-program against the staging API in WeChat Developer Tools and on iOS/Android. Only then set `USE_POLICY_V2` for the staged build.
8. Rehearse rollback with V1 reads still available. Keep V2 writes isolated; do not stop the legacy collector until the cutover window and replay procedure are approved.

## Current limits

- Source registry includes National, Jiangsu, Hunan, and Guangdong candidate channels; every channel defaults to disabled. Provincial list parsing filters cross-domain links so a province cannot accidentally ingest national articles as provincial documents.
- Page/detail collection, immutable object storage, revisions, attachment extraction, list/detail APIs, and authenticated source enablement are implemented in the V2 branch.
- Run one collector worker: it owns the HTTP/Firefox sessions and enforces per-host navigation/request spacing. Persisted origin cooldowns cover sibling columns and worker restarts; the base is `POLICY_SOURCE_COOLDOWN_SECONDS=300`, doubles up to one hour, and honors longer Retry-After values. A deferred task does not consume an attempt. This is not a distributed rate limiter for multiple concurrent workers.
- Previously stored documents remain readable when collection fails. List APIs expose the most recent successful collection time (not a guarantee that every source is current), and source failures remain visible. The home page preserves loaded cards after refresh failure, commits pagination only after success and ignores superseded responses. This is not a persistent offline cache across app restarts.
- Hunan's interpretation column contains unrelated reports and original policies; only titles explicitly matching 解读/图解/问答 are admitted by this adapter. This conservative rule needs sample review and does not establish classification accuracy. Hunan display/list dates take precedence over its page-generation `PubDate` metadata.
- The admin API supports source listing and enable/disable, task inspection, and audited classification correction. It is not a complete operations dashboard.
- WeChat login and account-bound favorites/follows are implemented behind the V2 API. Push delivery, migration of anonymous V1 favorites, COS staging credentials, Nginx routing, Android/iOS testing, and production migration remain rollout work.
- Do not point the V2 migration command at the live database until an independently verified backup and a reviewed cutover window exist.
