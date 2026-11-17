# Policy V2 review and rollout

This runbook describes a staged rollout. Nothing here changes production by itself.

## Local checks

From `backend/`, install the pinned V2 dependencies, then run:

```sh
python -m pytest -q
python -m compileall -q policy_v2 tests
python -m policy_v2.cli sources
```

From the repository root, run:

```sh
node --check miniprogram/utils/api.js
node --check miniprogram/app.js
node miniprogram/tests/api-v2.test.js
```

## Staging order

1. Create a private staging database and object bucket. Inject credentials through the deployment secret store; never commit `.env` or keys.
2. Install V2 dependencies and the matching browser with `pip install -r requirements-v2.txt` and `python -m playwright install firefox`. Start `uvicorn policy_v2.app:app` from `backend/` on a private port. Route `/api/v2/` through Nginx after health checks. The API imports and creates the V2 schema, but it does not start the collector.
3. Run one `python -m policy_v2.cli worker` service. Schedule `python -m policy_v2.cli discover` every 6 hours. Keep all sources disabled until their individual trial is reviewed.
4. Verify private object writes, hash checks, attachment extraction, failure retry, task recovery, and backup restoration in staging.
5. Migrate a copy of the legacy SQLite database with `python -m policy_v2.cli migrate /path/to/legacy.db`. Compare totals and ID mappings. Legacy rows have no fabricated raw snapshot. Global legacy favorites have no account identity and need a product decision before they can be assigned to user accounts.
6. Validate source adapters on a small, manually reviewed sample. The 2026-11-17 live check confirmed that Jiangsu's normative-document list/detail and interpretation list/detail parse, and both Guangdong policy/interpretation lists and sample details parse. NHC's plain HTTP request can return 412; the V2 fetcher now retries that response in Firefox and accepts it only when an NHC list or article body is present. Firefox retrieved the NHC normative-document list and sample detail in the latest probe. The NHC interpretation page returned a usable list in an earlier Firefox trial, but a repeated probe received 412 without a usable list; keep it paused until repeated runs are stable. The Jiangsu interpretation page links to NHC documents as well as Jiangsu content; list parsing accepts only province-hosted items. Hunan's two registered channels failed direct TLS negotiation and timed out in the local Firefox probe; keep them paused until ordinary access succeeds. Do not weaken TLS or automate challenge solving.
7. Test the mini-program against the staging API in WeChat Developer Tools and on iOS/Android. Only then set `USE_POLICY_V2` for the staged build.
8. Rehearse rollback with V1 reads still available. Keep V2 writes isolated; do not stop the legacy collector until the cutover window and replay procedure are approved.

## Current limits

- Source registry includes National, Jiangsu, Hunan, and Guangdong candidate channels; every channel defaults to disabled. Provincial list parsing filters cross-domain links so a province cannot accidentally ingest national articles as provincial documents.
- Page/detail collection, immutable object storage, revisions, attachment extraction, list/detail APIs, and authenticated source enablement are implemented in the V2 branch.
- The admin API supports source listing and enable/disable, task inspection, and audited classification correction. It is not a complete operations dashboard.
- WeChat login and account-bound favorites/follows are implemented behind the V2 API. Push delivery, migration of anonymous V1 favorites, COS staging credentials, Nginx routing, Android/iOS testing, and production migration remain rollout work.
- Do not point the V2 migration command at the live database until an independently verified backup and a reviewed cutover window exist.
