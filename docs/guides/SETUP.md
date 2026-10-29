# Local development

Running HalalLens from source: database, API and UI, tests, the narrator and Google SSO. Back to the [README](../../README.md).

```bash
git clone https://github.com/hamza-aziz-ai/HalalLens.git
cd HalalLens
cp .env.example .env          # then fill in the values; never commit .env
pipenv install --dev          # Python 3.14
```

**Database.** Postgres and MinIO are external. For a fresh database apply `database/schema.sql`; for an existing one apply the dated files in `database/migrations/` in order. `scripts/run_migrations.sh` does both and records applied files in `schema_migrations`; with `REQUIRE_EXISTING_DB=1` (production) it refuses to create the schema on an empty database. Production runs Postgres 17 (D-029); use 17 locally too, for example `postgres:17.11-trixie`.

```bash
createdb halallens_dev
DATABASE_URL=postgresql://user@localhost/halallens_dev bash scripts/run_migrations.sh
```

`20260728_security_hardening.sql` clears `user_sessions` (tokens are now stored as SHA-256 digests), so everyone signs in again once; it also adds the unique `(provider, event_id)` index on `payment_events`.

**API and UI.**

```bash
pipenv run uvicorn api.app:app --reload --port 8001      # http://localhost:8001/docs
cd ui && npm install && npm run dev                        # http://localhost:3000
```

Set `NEXT_PUBLIC_HALAL_API_BASE_URL` (in `ui/.env.local`) to the API origin. It is baked in at build time.

**Tests.**

```bash
pipenv run pytest                                   # backend; same command CI runs
cd ui && npm test && npm run lint && npm run build  # frontend
```

Tests must not need live Postgres, MinIO, an LLM or vendor APIs. The opt-in `tests/test_*_postgres.py` files run only when `HALALLENS_TEST_PG_DSN` points at a throwaway database (the docstring of `tests/test_watchlist_postgres.py` has a `docker run` line for one).

## Narrator

`NARRATOR_MODE` defaults to `rule_based` (the only path whose consistency with the verdict is guaranteed). With `NARRATOR_MODE=llm` (plus `LLM_PROVIDER`, `LLM_ENDPOINT`, `LLM_MODEL`, optional `LLM_API_KEY`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT`) the model is asked only about `compliant` / `non-compliant` results. Its text is shown only if it repeats the engine's verdict in a `screen_verdict` field and its summary, verdict and bullets pass a keyword check; otherwise, on any LLM error, and for `insufficient-data`, the rule-based narrator is used, and the label shown is always the engine's. **This is best-effort, not a guarantee:** a paraphrase the check does not know can still contradict the verdict, so the UI marks LLM text as AI-generated. `tools/preflight.py` requires the LLM endpoint to be reachable in `llm` mode. Set `LLM_MAX_TOKENS=0` and/or `LLM_TIMEOUT=0` to let the server decide limits (useful for reasoning-heavy models). The production setup (Ollama with `gpt-oss:120b-cloud`, D-022) is in README_ops.md, "LLM narration".

## Google SSO (optional)

Create a Google "Web application" OAuth client, then set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (`<api>/auth/google/callback`; behind Caddy in production `https://<domain>/api/auth/google/callback`) and `FRONTEND_BASE_URL`. The token is returned in the URL **fragment** (`/login#token=...`), never the query string, and the redirect must match `FRONTEND_BASE_URL` or the `halallens://` scheme. A failed sign-in redirects to `/login#error=<code>`. Google flows are bound to the starting browser by an HttpOnly cookie, so the UI and API must share one origin (the production `/api` setup, D-021).
