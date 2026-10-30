# HalalLens Ops Runbook

This guide captures day‑to‑day operations for running HalalLens in a pilot or early production environment.

## 1. Secrets & environment

| Variable                                | Purpose                                                                                                                                                                                                                                                      |
|-----------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `POSTGRES_*`                            | Database host, db name, user, password. `docker-compose.yml` connects to an external Postgres via `host.docker.internal`; `docker-compose-prod.yml` bundles a `postgres` service.                                                                          |
| `MINIO_*`                               | S3-compatible store for filing PDFs and backups (MinIO locally, Cloudflare R2 in production): host, port, keys, bucket, TLS, region.                                                                                                                       |
| `INDIAN_API_BASE_URL`, `INDIAN_API_KEY` | Indian Stock Market API endpoint + token for live market data/metrics.                                                                                                                                                                                       |
| `OPS_*`                                 | Ops alerting (SMTP + Slack). `.env.example` lists them all.                                                                                                                                                                                                  |
| `SMTP_*`, `ALERT_EMAIL_SENDER`, `ALERT_EMAILS_ENABLED` | Mail for sign-up and reset links and, with `ALERT_EMAILS_ENABLED=true`, compliance-flip alerts to subscribers (see Alert emails below). |
| `REQUIRE_EXISTING_DB`                   | `1` in production: `scripts/run_migrations.sh` refuses to create the schema on an empty database (D-029). |
| `HALAL_LOG_ROOT`                        | Where component logs live (default `./logs`).                                                                                                                                                                                                                |
| `LOG_LEVEL`                             | `DEBUG` / `INFO`. Set globally or per service.                                                                                                                                                                                                               |
| `NARRATOR_*`, `LLM_*`                   | Narrator configuration. Default `NARRATOR_MODE=rule_based`. In `llm` mode the model is asked only about conclusive verdicts and its text is best-effort (UI marks it AI-generated); `tools/preflight.py` requires the endpoint to be reachable in that mode. |

Store secrets in a `.env` file, Docker secrets, or whichever secret manager your platform provides. Rotate them periodically; when rotating DB passwords, recreate every service that reads them (`docker compose up -d --force-recreate`; a plain `restart` keeps the old environment).

### Deployment quick-start

1. Provision a host with Docker Compose v2. No GPU or LLM server is needed for the default rule-based narration; an LLM server is only needed if you set `NARRATOR_MODE=llm` (a compatible GPU if you self-host it).
2. Prepare external Postgres + MinIO/S3 endpoints (or reuse existing ones). Populate `.env` from `.env.example` with all `POSTGRES_*`, `MINIO_*`, `INDIAN_API_*`, `OPS_*`, and (only for the LLM narrator) `NARRATOR_MODE` / `LLM_*`.
3. Launch the stack:

   ```bash
   docker compose up --build -d
   ```

4. Verify:

   ```bash
   curl http://<api-host>:8001/health
   curl http://<api-host>:8001/ops/metrics   # admin session required
   ```

5. The `ingestion` and `evaluation` schedulers start with the stack (outside Docker, run `jobs.schedule_ingestion` under systemd or similar). Watch `/ops/metrics` and the ingestion heartbeat for failures.

### Uptime check

`.github/workflows/uptime.yml` requests `<UPTIME_URL>/api/health` every 30 minutes (three tries, 20 s apart). A failure opens one issue labelled `uptime`, or comments on the open one, which notifies the repository's watchers; the next success closes it. Set the repository variable `UPTIME_URL` (e.g. `https://halallens.in`) to turn it on; without it the job is skipped. GitHub disables scheduled workflows after 60 days without repository activity, so re-enable it under Actions if that happens. It checks that the site answers and, through `/api/health/billing`, that the payment reconciler runs (see Billing below); it does not check that ingestion or backups ran: read those in the service logs.

### PostgreSQL backups and restore

The `backup` service in `docker-compose-prod.yml` runs `jobs.backup_postgres` once a day (`BACKUP_INTERVAL_HOURS`, default 24). Each run writes a `pg_dump --format=custom` of the app database to `backups/postgres/<db>-<UTC timestamp>.dump` in `MINIO_BUCKET` (R2 in production), then deletes backups under that prefix older than `BACKUP_RETENTION_DAYS` (default 14). Old copies are deleted only after a successful upload; a failed run logs `Backup failed`, notifies through the ops notifier and retries after an hour. The dumps hold user accounts (emails, password hashes, session digests): keep the bucket private and the token scoped to it.

- Back up now: `docker compose -f docker-compose-prod.yml exec -T backup python -m jobs.backup_postgres` (one run inside the running service; `run backup ...` would append to its `--loop` entrypoint).
- **Use the API image's `pg_restore`.** The dumps are written by the API image's `pg_dump`, whose version follows the API base image (17 from Debian trixie), not the Postgres container. Production runs Postgres 17 since 2026-10-29 (D-029), so client and server now match. Historical, for dumps restored into a 14 server: Postgres 14's own `pg_restore` refused them (`unsupported version (1.16) in file header`), and the restore logged one harmless error, `unrecognized configuration parameter "transaction_timeout"` (a 17-only setting).
- Restore: download a `.dump` from the bucket (Cloudflare dashboard, or any S3 client) into `/opt/halallens/halallens.dump`, then stop the writers and restore into the running Postgres:
  1. `docker compose -f docker-compose-prod.yml stop api ingestion evaluation backup billing-reconcile`
  2. `docker compose -f docker-compose-prod.yml run --rm --no-deps -T -v "$PWD/halallens.dump:/tmp/restore.dump:ro" --entrypoint sh backup -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --clean --if-exists --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/restore.dump'`
  3. `docker compose -f docker-compose-prod.yml up -d`
- Restore drill: restore the newest dump into a throwaway `postgres:17.11-trixie` container started with `--network none`, run the API image's `pg_restore` inside its network namespace (`docker run --network container:<throwaway> --entrypoint pg_restore <api image> ... -h 127.0.0.1`), and compare `count(*)` per table with live. Last drill 2026-10-29 (into Postgres 14, before the upgrade): 20 of 20 tables matched, including 34,959 `market_data_snapshots` rows. Repeat monthly and after any Postgres or API base-image upgrade.

### Postgres major upgrade (14 -> 17, 2026-10-29)

**Done 2026-10-29** (cutover 17:35-17:38 UTC, v0.17.4; per-table counts and sequences matched; the record is in `docs/HANDOVER.md`). Kept as the runbook for the next major upgrade. Postgres 14 reaches end of life on 2026-11-12. The upgrade is a dump and restore into a new volume (D-029): `docker-compose-prod.yml` now runs `postgres:17.11-trixie` on the volume `postgres17_data`, and the old volume `postgres_data` (on the server `halallens_postgres_data`) keeps the 14 files untouched as the rollback. The database is small (21 MB), so the window is minutes; the site shows the maintenance page meanwhile, and the uptime workflow will open an issue during the window. Run everything on the VM in `/opt/halallens`. `OLD` is the release running now, `NEW` the first release with this change.

- **Checkpoints:** stop at A, B or C if a check fails and take that checkpoint's way back; nothing before W4 touches the old volume.
- **Credentials and tools:** every client command runs in a one-off container of the `backup` service (the API image: `pg_dump`, `pg_restore`, `psql` 17, credentials from `.env`). Dumps travel through stdin and stdout because the image runs as user 10001 and cannot read the private `upgrade/` directory.
- **`REQUIRE_EXISTING_DB=1`** makes `scripts/run_migrations.sh` refuse an empty database instead of creating a fresh schema, so a deploy onto the new, still-empty volume fails loudly instead of starting an empty site. Keep it in production's `.env` from now on.

```bash
cd /opt/halallens
C="docker compose -f docker-compose-prod.yml"
export API_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$($C ps -q -a api)")
OLD=$(git describe --tags --exact-match); NEW=vX.Y.Z   # NEW: the release with D-029
psqlc() { $C run --rm --no-deps -T --entrypoint sh backup -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -v ON_ERROR_STOP=1 -tA -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"; }
dumpdb() { $C run --rm --no-deps -T --entrypoint sh backup -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump --format=custom --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }

# P0, before the window (writers still running)
git status --short                       # must print nothing
echo "OLD=$OLD NEW=$NEW"                 # write both down
docker pull postgres:17.11-trixie
umask 077; mkdir -p upgrade
dumpdb > upgrade/rehearse.dump
docker run -d --rm --name pg17rehearse --network none -e POSTGRES_PASSWORD=x postgres:17.11-trixie
until docker exec pg17rehearse pg_isready -q -h 127.0.0.1; do sleep 2; done   # TCP: ready only after init
docker run --rm -i --network container:pg17rehearse -e PGPASSWORD=x --entrypoint pg_restore "$API_IMAGE" -1 --no-owner -h 127.0.0.1 -U postgres -d postgres < upgrade/rehearse.dump; echo "rc=$?"   # must be 0
docker rm -f pg17rehearse; rm upgrade/rehearse.dump
cat > upgrade/counts.sql <<'SQL'
SELECT 'table ' || table_name || ' ' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', table_name), false, true, '')))[1]::text
  FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
UNION ALL
SELECT 'seq ' || sequencename || ' ' || coalesce(last_value::text, 'unset')
  FROM pg_sequences WHERE schemaname = 'public'
ORDER BY 1;
SQL

# W1, freeze (compose still on 14)
$C stop api ingestion evaluation backup billing-reconcile    # Caddy now serves the maintenance page
psqlc -c "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"   # must be 0
psqlc < upgrade/counts.sql > upgrade/counts14.txt; wc -l upgrade/counts14.txt
dumpdb > upgrade/halallens-pg14.dump && sha256sum upgrade/halallens-pg14.dump | tee upgrade/halallens-pg14.dump.sha256
docker run --rm -i --entrypoint pg_restore "$API_IMAGE" -l < upgrade/halallens-pg14.dump | grep -c 'TABLE DATA'   # must be > 0
# Off-site copy under backups/upgrade/ (the nightly prune only touches backups/postgres/); prints the stored size
$C run --rm --no-deps -T --entrypoint sh backup -c 'cat > /tmp/d && python3 -c "from config import MINIO_BUCKET as b; from etl.minio_client import make_storage_client as m; c = m(); k = \"backups/upgrade/halallens-pg14.dump\"; c.fput_object(b, k, \"/tmp/d\"); print(c.stat_object(b, k).size)"' < upgrade/halallens-pg14.dump
stat -c %s upgrade/halallens-pg14.dump   # must equal the size printed above
# Checkpoint A. Way back: $C start api ingestion evaluation backup billing-reconcile   (still 14)

# W2, start 17 on the new, empty volume
sed -i '/^REQUIRE_EXISTING_DB=/d' .env && echo REQUIRE_EXISTING_DB=1 >> .env
git fetch -q --tags origin && git checkout -q "$NEW"
$C config -q
$C up -d --no-deps postgres
# The image's init server listens on the socket only, and the compose healthcheck can pass during init: wait over TCP
$C run --rm --no-deps -T --entrypoint sh backup -c 'until pg_isready -q -h "$POSTGRES_HOST" -U "$POSTGRES_USER"; do sleep 2; done'
psqlc -c "SELECT version()"                                                  # PostgreSQL 17.11 ...
psqlc -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"       # must be 0
# Checkpoint B. Way back: env -u API_IMAGE scripts/deploy.sh "$OLD"   (14 on the old volume)

# W3, restore (one transaction: a failure leaves the database empty, so a retry is safe)
$C run --rm --no-deps -T --entrypoint sh backup -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore -1 --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < upgrade/halallens-pg14.dump; echo "rc=$?"   # must be 0
psqlc -c "ANALYZE"
psqlc < upgrade/counts.sql > upgrade/counts17.txt
diff upgrade/counts14.txt upgrade/counts17.txt && echo IDENTICAL
# Checkpoint C. Way back: env -u API_IMAGE scripts/deploy.sh "$OLD"   (14 on the old volume)

# W4, release on 17
env -u API_IMAGE scripts/deploy.sh "$NEW"
$C exec -T backup python -m jobs.backup_postgres                          # one backup on 17 must succeed
docker volume ls | grep postgres                                        # halallens_postgres_data (14) and halallens_postgres17_data
```

Then sign in by hand and open a filing; `/api/health/billing` must report `ok` after the next reconcile (at most 15 minutes).

- **Rollback after W4:** `env -u API_IMAGE scripts/deploy.sh "$OLD"` boots 14 on the old volume with the data as of W1. Writes made on 17 since the cutover are lost unless you first stop the writers, dump 17 (`dumpdb > upgrade/halallens-pg17.dump`), roll back, stop the writers again, restore that dump into 14 and start the writers: `$C run --rm --no-deps -T --entrypoint sh backup -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore --clean --if-exists --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < upgrade/halallens-pg17.dump`. Never add `--exit-on-error` or `-1` there: 17 dumps contain `SET transaction_timeout`, which 14 rejects with one harmless error.
- **Point of no return:** the first real user or payment write on 17 (billing is in test mode today). After it, prefer fixing forward on 17.
- **Cleanup**, after 14 days and with the maintainer's OK: `docker volume rm halallens_postgres_data`, `rm -rf upgrade`, delete `backups/upgrade/halallens-pg14.dump` from the bucket, `docker image rm postgres:14`. Until then never run `$C down -v` or `docker volume prune`. For the 2026-10-29 upgrade a one-time cron job on the server (not in this repository) removes the old volume on 2026-11-13; afterwards check which of the other items remain and do them by hand.

### Billing (Razorpay, one-time purchases)

Plans are one-time Razorpay Orders; nothing renews automatically. Each paid order, trial and pre-ledger period is a row in `subscription_grants`, and access is derived from them (D-024): a timed purchase (Starter, Annual) made while timed paid time runs starts when it ends, a refund removes only its own purchase's time. Lifetime takes effect when paid: it is the current plan from its settlement time, any timed grants keep their dates underneath, and refunding the Lifetime returns whatever timed access remains (with its original end) or leaves the account free (D-024 amendment, 2026-10-30).

- **Lifetime takes effect when paid (one-off repair after deploying it):** the API rewrites a stored projection only after its renewal date passes, so an account that bought Lifetime under the old rule keeps showing its timed plan (for example Annual until 2027) until then. After deploying, re-project every user with a Lifetime grant through the locked `refresh_entitlement`; it prints each user id and the projection written (`plan` should be `lifetime` for an unrefunded Lifetime). It changes only the `users` projection, never a grant, and is safe to run again:

  ```bash
  # exec in the running service: a bare `compose run` uses API_IMAGE's default
  # (the local image halal-lens-api), which may be an old build.
  docker compose -f docker-compose-prod.yml exec -T billing-reconcile python3 -c '
  import api.billing as billing
  from database.database_manager import BSEDatabaseManager
  db = BSEDatabaseManager(min_connections=1, max_connections=2)
  with db.get_connection() as conn, conn.cursor() as cur:
      cur.execute("SELECT DISTINCT user_id FROM subscription_grants WHERE duration IS NULL ORDER BY user_id")
      user_ids = [row["user_id"] for row in cur.fetchall()]
  for user_id in user_ids:
      print(user_id, db.refresh_entitlement(user_id, billing.project))
  '
  ```

  **Rollback:** deploy the previous tag (`scripts/deploy.sh <previous tag>`), then run the same command so the projection follows the old rule again (Lifetime queued behind the timed plan). No data changes either way: grants are the truth and both rules read the same rows.
- **Before deploying the first release with D-024**, apply `database/migrations/20261029_subscription_grants.sql` (it is idempotent, and creates a legacy grant that keeps each current subscriber's exact end date). Rehearsed on a restored production copy on 2026-10-29.
- **Refund due:** if a payment lands while Lifetime already covers the user (two checkouts were open), or a credited Lifetime order's price no longer holds (D-030, below), the order gets status `refund_due` with a `refund_due_reason` (`lifetime_held`, `price_expired`, `credit_changed`; NULL on orders from before D-030 means `lifetime_held`), nothing is granted, and the API logs `REFUND DUE ... reason=...`. The amount owed is the charged `amount`, never the list price. Under TEST keys the reconciler refunds it automatically (see Automatic refunds below); otherwise refund it in the Razorpay dashboard: `SELECT order_id, user_id, amount, list_amount, credit_amount, refund_due_reason, payment_id FROM razorpay_orders WHERE status = 'refund_due';`
- **Upgrade credit at checkout (D-030):** Lifetime is priced as list price minus the unused share of what the buyer paid for timed plans (`razorpay` grants only; trials and pre-ledger grants give nothing; a purchase with an open billing item or an unsettled refund request gives nothing). The order stores `list_amount`, `credit_amount`, `amount` (charged), `priced_at`, `price_valid_until` (15 minutes later) and the evidence in `credit_detail`; Razorpay is asked for the charged amount. A price holds for a payment attempt Razorpay created by `price_valid_until`, even if it is captured later. A Lifetime with no credit (nothing eligible) is an ordinary order: list price, no pricing terms, no window. A refund raises `credit_conflict` only for a payment that actually gave credit (`credit > 0` in `credit_detail`). A payable below ₹1 opens no checkout (the buyer is told to contact support): grant Lifetime by hand only after checking the grants, or refund the timed purchases and let the buyer pay the list price. Inspect a credited order: `SELECT order_id, amount, list_amount, credit_amount, priced_at, price_valid_until, credit_detail FROM razorpay_orders WHERE credit_version IS NOT NULL ORDER BY created_at DESC LIMIT 20;`. A credited order whose payment has no `created_at` is left claimable (webhook answers `retry`); the reconciler tracks the payment as `pending` and settles it from the fetched payment.
- **Credit conflict (D-030, alert only):** when a refund is recorded for a payment whose purchase gave credit to a settled Lifetime order, `billing_tracked` gets a `credit_conflict` item (keyed by refund id, `order_id` = the Lifetime order) and the operator gets "Billing needs attention: credit_conflict". Nothing changes automatically: the buyer keeps Lifetime. Decide by hand: either refund the Lifetime (in full, which revokes it, or partly, which keeps it) or adjust it with the buyer first, then resolve the item: `UPDATE billing_tracked SET resolved_at = NOW() WHERE kind = 'credit_conflict' AND provider_id = '<refund id>';`. Open items: `SELECT provider_id, order_id, last_status, first_seen FROM billing_tracked WHERE kind = 'credit_conflict' AND resolved_at IS NULL;`. The reconciler never re-checks or resolves them.
- **Upgrade credit rollback:** deploy the previous tag (`scripts/deploy.sh <previous tag>`). The migration `20261030_lifetime_upgrade_credit.sql` is additive and stays: old code ignores the new columns, but it would settle an open credited order without its checks and would not open `credit_conflict` items, so first list open credited orders (`SELECT order_id FROM razorpay_orders WHERE credit_version IS NOT NULL AND status IN ('created', 'attempted');`) and watch them by hand until they are paid or abandoned. The widened `billing_tracked` kind check is harmless to old code.
- **Refunds that match no grant** (refund-due orders, or old orders the migration could not link) are logged `matches no grant: review by hand`; adjust access by hand only after checking the user's grants.
- **Reconciler** (`billing-reconcile` service, `jobs/reconcile_payments.py`, every 15 min): sweeps Razorpay refunds, then payments, created since its checkpoint (from the first order; at most 7 days per run) and re-sweeps one older day per run; settles captured payments the webhook missed (alert: "a Razorpay webhook was missed"; check that the webhook is still enabled, Razorpay disables it after 24 h of failures), applies refunds made in the dashboard, links pre-ledger purchases to their payment when exactly one attempt ever succeeded, and keeps everything else in `billing_tracked` until resolved: `pending` (re-checked by id, daily after a week, never retired by age), `duplicate` and `refund_due` (money to refund; refunded automatically under TEST keys, see below), `mismatch`, `legacy_review`, `failed_refund`, `lookup_error`. Alerts go through the ops notifier on first sight, then daily. Open items: `SELECT kind, provider_id, order_id, reason, last_status, first_seen FROM billing_tracked WHERE resolved_at IS NULL;` After handling one by hand, set `resolved_at = NOW()`. State and last error: `SELECT * FROM billing_reconcile_state;` Run once by hand: `docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint python3 billing-reconcile -m jobs.reconcile_payments`. Razorpay GETs retry a rate limit (429) or a 502/503/504 twice, waiting as `Retry-After` asks (at most 10 s), so only a limit that outlasts that stops the run with a "Razorpay request failed" warning; the next run resumes from the checkpoint. Discovery is best effort over Razorpay's list APIs; completeness beyond the overlap and the audit is not guaranteed.
- **Automatic refunds** (TEST keys only, by code; live refunds need their own reviewed change): the reconciler refunds a proven `duplicate` payment or a `refund_due` payment in full. The request (amount, body, `X-Refund-Idempotency` key) is stored in `refund_actions` before it is sent; a retry first looks for a refund carrying that key in its notes, then re-sends the identical request. A partial or pending refund already on the payment, a parameter-mismatch 409 or any other refusal means no automatic refund: the action is `blocked` and you are alerted; refund by hand in the dashboard and the reconciler closes the obligation (any processed refunds reaching the full amount count). `SELECT payment_id, reason, amount, state, provider_refund_id, last_error, obligation_settled_at FROM refund_actions;`
- **Heartbeat:** `GET /api/health/billing` (public: status and age only) reports `ok` when the reconciler succeeded within 60 minutes, else `stale` / `never`, or `disabled` without Razorpay keys. The uptime workflow checks it with `/api/health` and keeps its issue open until both pass; set the repository variable `BILLING_EXPECTED=true` so `disabled` also fails. `ok` means the job runs, not that no item is open.
- Refunds are recorded once per refund id against the payment they refund (D-025). Partial refunds keep access until the funding payment's refunds reach the order amount; refunding another payment attempt on the same order never touches access; refunds of pre-ledger purchases are logged `funding payment unknown, review by hand`.

### Alert emails (compliance flips, D-031)

The evaluation scheduler (`evaluation` service) observes every watched symbol after each precompute and emails each compliance flip to the subscriber's own verified address, through the same SMTP settings as the sign-up mail (`SMTP_*`, `ALERT_EMAIL_SENDER`, links on `FRONTEND_BASE_URL`). Only one sender runs at a time (advisory lock `(20261030, 1)`); a second one logs "Another alert sender holds the lock; skipping". Only verified, opted-in users with paid access now are mailed; everyone else is rebaselined silently. Delivery is at least once: a crash after SMTP accepted a message resends it next run with the same Message-ID.

- **Switch:** `ALERT_EMAILS_ENABLED=false` is the default; production runs with `true` since 2026-10-30 (v0.20.0). While it is off, each run still records flips but silently rebaselines every pending row (`notified = last`), so nothing accumulates and nothing replays when you switch it on. Set it to `true` in `.env` and recreate the `evaluation` service (`docker compose -f docker-compose-prod.yml up -d evaluation`) to start sending; set it back to `false` to stop at once.
- **Before the first enable (received-mail smoke check):** subscribe a test account on your own address, watch a symbol, and with the switch on let one flip go out (or wait for a real one). Open the received message's original headers and check `DKIM-Signature` with `dkim=pass`, `spf=pass` and `dmarc=pass` in `Authentication-Results`, `From` on your `ALERT_EMAIL_SENDER` domain, a `Message-ID` of the form `<alert-...@domain>`, and the "Manage alerts" link opening the account page. If DKIM or SPF fails, switch it off and fix the provider's DNS records first.
- **Logs:** `logs/evaluation_scheduler/...` carries one line per run, `Alert emails: {...}` with counts (`flipped`, `sent`, `silenced`, `deferred`, `failed`, `failed_terminal`, `rebaselined`, `error:<ExceptionClass>`), never addresses. Failures also raise an ops alert (`OPS_*`) with the same counts.
- **Stuck rows:** after 5 SMTP failures (backoff 15 min, 30 min, 1 h, 2 h) a row stops (`notify_failed_at`) until its verdict changes again. To retry after fixing SMTP: `UPDATE watchlist_entries SET notify_attempts = 0, notify_next_at = NULL, notify_failed_at = NULL WHERE notify_failed_at IS NOT NULL;`
- **Repair procedure (recompute or data repair while alerts are on):** a recompute can flip many verdicts at once, and subscribers should not get a mail per repaired row. 1) Set `ALERT_EMAILS_ENABLED=false` and recreate `evaluation`. 2) Run the repair or recompute (see "Stored data repair"). 3) Let one scheduler run pass (check the `Alert emails:` log line shows `rebaselined`): every changed verdict is now the silent baseline. 4) Set it back to `true` and recreate `evaluation`.
- **Opt-out:** users switch alert emails off on the account page (`PUT /account/alert-emails`, works after paid access ends). There is no one-click unsubscribe link or `List-Unsubscribe` header yet; add them (RFC 8058) when volume or a provider's bulk-sender rules require it.

### Docker Hub pages

The Docker Hub descriptions of `halallens-api` and `halallens-ui` come from `docs/dockerhub/*.md` (full description) and `.github/workflows/dockerhub-description.yml` (short description). The workflow runs when those change on `main`, or by hand (Actions, Docker Hub descriptions, Run workflow). It uses `DOCKERHUB_NAMESPACE` and `DOCKERHUB_TOKEN` from the `publish` environment; updating a description needs a token with Read, Write, Delete access. Categories (up to three per repository) can only be set in Docker Hub's repository settings, not through the API.

### LLM narration (Ollama, optional)

The Explain-Why text is rule-based by default. To let a model rewrite it for conclusive verdicts (D-022):

1. Add `llm` to `COMPOSE_PROFILES` and set `NARRATOR_MODE=llm`, `LLM_PROVIDER=ollama`, `LLM_ENDPOINT=http://ollama:11434/api/chat`, `LLM_MODEL=gpt-oss:120b-cloud` in `.env`, then deploy.
2. Link the daemon to the Ollama account once: `docker compose -f docker-compose-prod.yml exec ollama ollama signin`, open the printed link in a browser signed in to ollama.com and connect the device. The key lives in the `ollama_data` volume, so restarts and updates stay signed in; deleting the volume or removing the device on ollama.com signs it out ("You need to be signed in" in the API log).
3. Check: `docker compose -f docker-compose-prod.yml exec ollama ollama run gpt-oss:120b-cloud "Say ok"`.

Calling ollama.com directly with an API key needs paid credits (HTTP 402); the signed-in daemon uses the account's free allowance, whose limits are not published. The API therefore makes at most 6 model calls a minute and skips the model for 60 s after 3 failures in a row; any failure, timeout or text that contradicts the verdict falls back to the rule-based explanation. Only public filing figures, the symbol and the verdict are sent, never user data; prompts and replies are not logged. Trade-off: the VM holds a signed-in device on the maintainer's Ollama account, so anyone who controls the VM can spend that allowance.

### Indian Stock API quota

The vendor plan is small (the free plan allows 500 requests per month). Every vendor call goes through `market_data/indian_api.py::_request_json`, which enforces `INDIAN_API_MONTHLY_LIMIT` (production default 450) with a counter in `cache/indian_api_quota.json` in the persistent `api_cache` volume, so the cap survives restarts. At the cap the app logs `Indian API monthly limit reached` and falls back to stored data and the free Bhavcopy files. In production the ingestion and evaluation schedulers run with the vendor turned off, so the quota is spent only on users' on-demand lookups. The API key is sent only in the `X-API-Key` header, never in a URL.

### Production deploys (`scripts/deploy.sh`)

On the server, from the checkout that holds `.env` (production: `/opt/halallens`):

```bash
git fetch --tags && git checkout vX.Y.Z   # first time only, to get the script
scripts/deploy.sh vX.Y.Z
```

The script checks out the release tag (compose file, Caddyfile, migrations), then:

- **Pull mode** (recommended): with `IMAGE_REPOSITORY` in `.env` (e.g. `ghcr.io/<owner>` or `docker.io/<namespace>`), it pulls `halallens-api` and `halallens-ui` for that tag: the images CI tested, smoke-tested, Trivy-scanned and published with SBOM and provenance. Nothing is built on the server. Wait for the release's Publish images run to finish first; if the tag is not published yet, the pull fails before anything is restarted.
- **Build mode** (default): without `IMAGE_REPOSITORY`, it builds the images on the server from the tag.

Either way it starts the stack, waits for the API health check, prints the service states and smoke-tests `/api/health`, `/api/openapi.json`, `/` and `/products/` through Caddy; a non-200 makes it exit non-zero. **Rollback:** run it again with the previous tag (migrations are forward-only: see `docs/ROLLBACK.md`). The dashboard's support address is part of the UI image: the publish workflow bakes in the repository variable `SUPPORT_EMAIL`, and build mode uses `SUPPORT_EMAIL` from `.env` (default `support@<HALAL_APP_DOMAIN>`). The GitHub badge in the top-right corner works the same way: the repository variable `REPO_URL` (default: this repository) or `REPO_URL` in `.env` in build mode; set it to `none` to hide the badge, for example before the repository goes private.

**During a deploy** the api and ui containers restart for a few seconds. The front Caddy then answers with `caddy/maintenance.html` (503, `Retry-After: 30`; the page checks every 5 s and returns to the site by itself), and `/api/*` with a JSON 503. Inside the dashboard, `ui/components/maintenance-overlay.tsx` shows the same screen on its own: when an API call meets an outage (a 503 with `Retry-After`, or Cloudflare's 502/504/520-530), or a 30 s check while the tab is visible fails; it confirms with `/health` first and reloads the page once the site answers again. Tested on production 2026-10-29: dashboard container stopped and tunnel stopped, 90 s each. Cloudflare's own "Bad gateway" page appears only when Caddy, cloudflared or the VM itself is down. Every 502 is avoided on purpose: Cloudflare replaces an origin 502 with its own page, so upstream failures in the API (Razorpay, Google) answer 503. Unknown paths get the dashboard's 404 page (`ui/app/not-found.tsx`, exported as `404.html`).

### Cloudflare maintenance Worker (origin down)

The front Caddy's maintenance page cannot help when Caddy, cloudflared or the VM itself is down; Cloudflare then shows its own error page. `cloudflare/maintenance-worker.js` covers that case on the free Workers plan: it passes every request to the origin and answers a 503 maintenance page only when Cloudflare reports the origin unreachable (502, 504, 520 to 527, 530 = tunnel down) or the fetch fails.

Deploy once from the Cloudflare dashboard (no token needed):

1. **Workers & Pages → Create → Worker**, name it `halallens-maintenance`, deploy the starter, then **Edit code**, replace everything with `cloudflare/maintenance-worker.js` and **Deploy**. Under **Settings**, turn **Observability** logs off (they would record visitor requests).
2. **Settings → Domains & Routes → Add → Route:** zone `halallens.in`, route `halallens.in/*`, failure mode **Fail open** (if the Worker errors or the free plan's 100,000 requests a day run out, traffic goes straight to the origin).
3. **Websites → halallens.in → Workers Routes → Add route:** `halallens.in/api/*` with Worker **None**, so API calls and Razorpay webhooks never pass through the Worker.
4. Check: `curl -sI https://halallens.in/` still returns 200, and `/api/health` 200. The real test is the next time the tunnel is down (the page should show instead of Cloudflare's).

The page is an exact copy of `caddy/maintenance.html` (a dashboard Worker cannot import files), so visitors see the same page whether a container restarts or the whole origin is down; `tests/test_maintenance_page.py` fails when the copies differ. After changing the page, paste the Worker again.

### Published images

`publish-images.yml` runs when release-please publishes a release, or by hand (Actions → Publish images → Run workflow, with an existing tag) to retry. It waits for CI to pass on the released commit, builds `halallens-api` and `halallens-ui` natively for amd64 and arm64, runs the container and Caddy smoke tests, scans with Trivy (fails on fixable CRITICAL findings; HIGH and unfixed CRITICAL are listed in the run summary; reviewed exceptions go in `.trivyignore` with a reason and expiry), then pushes `vX.Y.Z-amd64` and `vX.Y.Z-arm64`, joins them into `vX.Y.Z`, and moves `latest` only for the newest release. A version tag that already exists is never overwritten.

- GHCR (`ghcr.io/<owner>/halallens-*`) needs no setup. New packages start private: make each one public once under the repository's Packages → Package settings (the HalalLens packages already allow anonymous pulls).
- Docker Hub needs the repository variable `DOCKERHUB_NAMESPACE` (account name) and the secret `DOCKERHUB_TOKEN` (an access token with Read & Write) in the `publish` environment, which only `main` and `v*` tags may use. Without them only GHCR is published.

### Images and volume ownership

One Python image (`api.Dockerfile`) runs every Python role: the API by default, and preflight, migrations, both schedulers, the backup and the payment reconciler through the commands in the compose files. It runs as the unprivileged user `10001:10001` and can write only to `cache/`, `downloads/`, `logs/`, `logs_runtime/` and `/tmp`. New named volumes mounted there take that ownership automatically. A volume created by an older image that ran as root keeps root ownership; fix it once with `docker run --rm --user 0 -v <volume>:/v halal-lens-api chown -R 10001:10001 /v`. The development compose file bind-mounts the working tree and runs these services as root on purpose.

### Exposing the site: Caddy TLS or Cloudflare Tunnel

`docker-compose-prod.yml` serves the dashboard at `/` and the API under `/api/` on `HALAL_APP_DOMAIN`. Pick one way in:

- **TLS (default, `CADDY_MODE=tls`):** point the domain's DNS at the host, open ports 80 and 443, set `ACME_EMAIL`. Caddy gets the certificates.
- **Cloudflare Tunnel (`CADDY_MODE=tunnel`):** no open web ports and no certificates on the host; the domain's DNS must be on Cloudflare.
  1. Cloudflare Zero Trust → Networks → Tunnels → create a `cloudflared` tunnel; copy its token.
  2. Add a public hostname: the domain (e.g. `halallens.in`), service `http://caddy:80`.
  3. In `.env`: `CADDY_MODE=tunnel`, `CADDY_SITE_ADDRESS=:80`, `CADDY_BIND=127.0.0.1`, `COMPOSE_PROFILES=tunnel`, `CLOUDFLARE_TUNNEL_TOKEN=<token>`.
  4. `docker compose -f docker-compose-prod.yml up -d`; the tunnel shows as Healthy in the dashboard.
  5. Keep the host's firewall (e.g. the OCI security list) closed to 80/443: the API trusts Cloudflare's `Cf-Connecting-Ip` in this mode, so Caddy must be reachable only through the tunnel.

## 2. Schema migrations

1. Pull latest `main`.
2. Apply any new files in `database/migrations/` in chronological order. `scripts/run_migrations.sh` does this and records applied files in `schema_migrations` (set `DATABASE_URL`, or `POSTGRES_*`). A single file can also be applied with `psql -h <host> -U <user> -d <db> -f database/migrations/<timestamp>_<name>.sql`.
3. Restart the API if columns changed.

Never skip migrations; the backend expects the schema to match.

## 3. Ingestion/backfill operations

### Scheduled ingestion

- Run `pipenv run python -m jobs.schedule_ingestion` as a service (systemd, supervisor, container).  
- Environment variables: `INGESTION_INTERVAL_MINUTES`, `OPS_*` for alerts.
- Logs: `logs/scheduler/<Year>/<Month>/scheduler.log`.
- Metrics: `logs/metrics/ingestion_metrics.jsonl`.
- Recommended cadence: hourly. During volatile earnings seasons drop to 15 minutes temporarily, then revert to hourly once filings clear. Watch `/ops/metrics` for consecutive failures.

### Manual backfill

To ingest a date range:

```bash
pipenv run python -m jobs.ingest_bse --from-date 20251009 --to-date 20251009 --save-cache
```

`--save-cache` stores raw JSON in `cache/` for audits; clean it when finished.

**Evaluations.** For filings with no evaluation yet use `jobs.precompute_evaluations` (the scheduled path; it selects them directly). `jobs.backfill_evaluations` without flags also skips filings that already have ratios, but it reads a window of the newest filings with evaluated rows first (`--limit`, default 500), so it can miss them. To repair evaluations computed by older ratio logic, use the recompute mode: `python -m jobs.backfill_evaluations --recompute --report dry_run.csv` (dry run), then `--recompute --report write_run.csv --write` (a new report name each run; an existing file is refused). It re-evaluates rows that already have ratios from the **current** stored inputs (snapshot, current governance overrides for receivables, liquid assets and non-halal income) and the stored market caps passed unchanged to the engine. It never calls the vendor or Bhavcopy and skips rows with no stored market cap. It publishes exactly like every other writer (D-027): the anomaly detector runs, and any open quality issue, of any type, gives `needs-review`. The dry run simulates that publication without writing anything; the CSV's `quality_issues` column lists the issue types that would be open and `ratio_anomaly` says whether the detector's row would be opened, updated or resolved. It is not a replay of an earlier dry run: the `--write` run re-reads the database, and before each write it re-reads the filing's inputs and checks, under the filing's lock, that the stored evaluation, the open issue types and the resulting pair still match the preview; a row that changed is skipped and logged as `Recompute skipped ... stale` (the CSV still shows its preview), so rerun with a new report for those. The CSV is evidence, not a backup: take a `pg_dump` of `filing_evaluations` and `data_quality_issues` first; each write commits on its own, so a failure mid-run leaves earlier rows written. Restart every API worker afterwards (narration caches are per process).

**Repair after D-027.** Before D-027 the jobs stored the engine's pair even while a filing had an open quality issue, so some stored rows can be conclusive next to an open issue (the API masks them on every read, but `/alerts/check` and anyone reading the table see the stored row). The production volume is unknown; inventory first, read-only:

```sql
SELECT fe.symbol, fe.filing_date, fe.verdict, array_agg(q.issue_type) AS open_issues
  FROM filing_evaluations fe
  JOIN data_quality_issues q
    ON q.symbol = fe.symbol AND q.filing_date = fe.filing_date AND q.resolved_at IS NULL
 WHERE fe.verdict IS DISTINCT FROM 'needs-review'
 GROUP BY fe.symbol, fe.filing_date, fe.verdict;
```

Then take the dump, run the dry run with `--limit` at least the number of evaluated filings (`SELECT count(*) FROM filing_evaluations WHERE ratios IS NOT NULL AND ratios <> '{}'`), check that every inventoried row appears in the CSV with `new_verdict = needs-review`, review the other transitions (a resolved stale anomaly can turn `needs-review` back into the engine's pair), and only then run `--write` with a new report. Resolving an issue never restores a verdict by itself: after an operator resolves issues, the next evaluation or this recompute does. Do not run it against production without the maintainer.

### Stored data repair (D-028)

D-028 stopped the mappers from guessing `liquid_assets`, the prohibited-income base, net interest and dividends paid, but it changes only new extractions. Rows written before it can still hold those values, and `--recompute` re-reads them as they are, so repairing them is a separate, reviewed step. There is no tool for it yet; nothing below has been run against production, and each step needs the maintainer's review.

1. **Inventory.** List what may carry a rejected mapping: `financial_snapshots` rows with `liquid_assets`, `non_halal_income` or `interest_income` set; the PDF metric cache objects under `metrics/v4/` in the filing bucket (new runs use `metrics/v5/`, so the old ones are no longer read but still exist); `cache/` JSON written by `--save-cache`; and every `governance_overrides` row (some were written by the vendor enrichment, `"Structured governance metrics from Indian API"`).
2. **Re-extract from retained evidence.** For each affected filing, run the current extractor on the same retained artifact (the stored PDF or structured attachment) and compare field by field. Set a field the current rules no longer produce to NULL; never keep the old value because nothing replaces it. Where no artifact was retained, invalidate the affected fields (NULL) instead of trusting them.
3. **Review overrides.** Overrides win over snapshots on read (`COALESCE`), so a vendor-written `non_halal_income` ("Other, Net") or derived `liquid_assets` survives a snapshot repair. Remove or confirm each one by hand; keep a record of what changed.
4. **Preview, then recompute.** Take a `pg_dump` of `financial_snapshots`, `governance_overrides` and `filing_evaluations`, then run `python -m jobs.backfill_evaluations --recompute --report repair_dry_run.csv` and review it (expect many `insufficient-data` verdicts) before `--recompute --report repair_write.csv --write`. Recompute uses the stored market caps, so the only change is the repaired inputs.

## 4. Logs & monitoring

- Files reside under `logs/<component>/<Year>/<MonthName>/component.log`. Rotations include the date suffix.
- Example: `tail -f logs/api/2025/December/api.log`
- Ship logs to S3/Vector via your preferred agent; prune older months with `find logs -type f -mtime +90 -delete`.
- Ops notifications: configure `OPS_SMTP_*`, `OPS_EMAIL_*`, and/or `OPS_SLACK_WEBHOOK`. Failures produce “ERROR” emails/Slack messages with tracebacks; recoveries emit “INFO” alerts. Set `OPS_EVENT_HISTORY` (default 40) to control how many recent alert records are retained/returned by the API.
- Metrics (JSONL) can be ingested by Promtail/Vector for dashboards (success/failure counts, duration). The API also aggregates these into `GET /ops/metrics`, which surfaces the most recent ingestion runs, market-data alert history, and LLM narration failures—ideal for Grafana tables/cards without scraping raw files.
  - `monitoring/notifier.py` drives the alerts. To test, export the `OPS_*` variables and call `OpsNotifier("api").notify("INFO", "testing")` from a REPL (the module has no command-line entry point).
  - The ingestion scheduler writes JSON lines to `logs/metrics/ingestion_metrics.jsonl`. Quickly summarize them with:

    ```bash
    python tools/metrics_inspector.py logs/metrics/ingestion_metrics.jsonl
    # or tail the last N runs
    python tools/metrics_inspector.py --tail 10
    ```

    Forward the JSONL file to Grafana/Prometheus by pointing Promtail/Vector at it. A minimal Promtail scrape config:

    ```yaml
    - job_name: halallens_ingestion
      static_configs:
        - targets: [<host>]
          labels:
            __path__: /home/halal/logs/metrics/ingestion_metrics.jsonl
            job: halallens-ingestion
    ```

## 5. Manual data quality review

- Use the dashboard “Feedback queue” to triage reports. Reviewers (admins) add notes and mark entries resolved.
- To suppress a filing's verdict temporarily, open a data-quality issue for it with `BSEDatabaseManager.record_quality_issue(symbol, filing_date, issue_type, details)` (run it with `python3 -c` inside the `evaluation` container, like the Billing re-projection above). It takes the filing's lock and downgrades the stored result to `needs-review` at once, and every filing route and alert observation then sees `needs-review` (D-027). Never edit `filing_evaluations` by hand: `publish_filing_evaluation` is its only writer. Once corrections exist, `resolve_quality_issues` and re-evaluate (the precompute picks the filing up when its snapshot or override is newer, otherwise `--recompute`); resolving alone never restores a verdict.
- Record manual overrides/notes in `feedback_reports.review_notes` to keep an audit trail.
- For AAOIFI-specific fixes (receivables/liquid/non-halal income), leverage the “Governance overrides” card in the dashboard or call `/governance/overrides` via API. Overrides live in the `governance_overrides` table and are applied before ratios execute. Since D-028 an override is the only source of the prohibited-income base (`non_halal_income`), so no filing reaches `compliant` without one; record its source and reason, because overrides carry no declared contract.

## 6. Realtime symbol lookups (Indian API fallback)

- Populate `INDIAN_API_BASE_URL` and `INDIAN_API_KEY` in `.env`. Without these the API can only rely on stored filings and a realtime BSE fetch.
- When a paid user hits `GET /filings/{symbol}?refresh=true` (or the symbol has no usable stored filing), FastAPI first tries a realtime BSE fetch; if that yields no filing, it will:
  1. Grab company metadata + financial statements from the Indian Stock Market API.
  2. Persist the synthetic filing to `announcements`, `financial_snapshots`, `market_data_snapshots`, and `indianapi_snapshots`.
  3. Immediately compute AAOIFI ratios so subsequent `/filings/{symbol}` calls read from Postgres like any other entry.
- You can verify the persistence by running:

  ```bash
  curl -H "Authorization: Bearer <paid-session-token>" "http://<api-host>:8001/filings/TCS?refresh=true"
  psql -X -U $POSTGRES_USER -d $POSTGRES_DB -c \
      "SELECT symbol, filing_date, confidence FROM announcements ORDER BY filing_date DESC LIMIT 3;"
  ```

- Failures are logged under `logs/api/YYYY/Month/api.log` (e.g. `Failed to persist Indian API snapshot for <symbol>`). Re-run the refresh request once the upstream API recovers or you adjust the API key/rate limits.

## 7. Disaster recovery

- **Postgres**: snapshot nightly (pg_dump or managed backup).  
- **Filing PDFs** (S3-compatible bucket, Cloudflare R2 in production): copy the bucket elsewhere with rclone; PDFs can also be re-downloaded from BSE by re-running ingestion.  
- **Cache/downloads**: not critical—rebuildable by re-running ingestion.  
- **.env** / secrets: store in a secure vault and version them with change history.
- **Log retention**: rotate monthly via the existing folder structure. Prune anything >90 days unless compliance demands longer (`find logs -type f -mtime +90 -delete`). Archive `logs/metrics/*.jsonl` after importing into your dashboarding stack.

## 8. Backfills & secret rotation runbook

### Running historical backfills

1. Decide the date range (BSE is noisy; keep batches ≤ 2 weeks). Example:

   ```bash
   pipenv run python -m jobs.ingest_bse --from-date 20241101 --to-date 20241107 --save-cache
   pipenv run python -m jobs.precompute_evaluations --lookback-days 30   # evaluate filings that still need one
   ```

2. Watch `logs/ingestion/` for errors; resolve missing market data by re-running just the affected symbols.
3. After a successful batch, commit or archive the cache files if you need provenance; otherwise, prune `cache/`.

### Rotating secrets / credentials

1. Store all sensitive values in your vault of choice (1Password, Vault, AWS SM, etc.). Never edit `.env` directly on production hosts.
2. When a credential changes (Indian API key, SMTP password, DB user):
   - Update the vault and regenerate the `.env` from template (`cp .env.example .env && edit`).
   - Recreate the containers so they pick up the new env values (`docker compose up -d --force-recreate`; `docker compose restart` keeps the old environment).
   - Confirm `GET /health` and the ingestion heartbeat update.
3. Record the change in your ops log and destroy/rotate the old secret if applicable.

Keep this runbook alongside `README.md`; update both whenever operational requirements change.

## 9. Troubleshooting checklist

- `GET /health` returns `{"status": "ok"}` – liveness only: it does not touch the database. With Razorpay configured, `GET /health/billing` answers 503 when the database is unreachable.  
- Scheduler heartbeat: check `/tmp/ingestion_heartbeat.txt` timestamp (or your custom path).  
- Persistent Indian API failures: inspect `logs/market_data/` and consider adjusting API rate limits, refreshing the key, or falling back to Bhavcopy-only mode temporarily.  
- `preflight` fails with an LLM endpoint error: the LLM endpoint is unreachable while `NARRATOR_MODE=llm`. Fix the endpoint or set `NARRATOR_MODE=rule_based`. Narration errors fall back to the rule-based narrator and show up in `/ops/metrics`.
- Feedback queue empty but users reported issues: check `logs/api/.../api.log` for errors around `/feedback` endpoints.

## 10. Mobile app notes

- `halallens-mobile/` is a Flutter **platform scaffold only**: it has no `lib/` Dart source and cannot build. There is no mobile client to operate.
- The API still accepts the `halallens://auth/login` redirect on `/auth/google/start` for a future app.
