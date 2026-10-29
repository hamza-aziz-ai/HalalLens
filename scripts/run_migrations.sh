#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

MIGRATIONS_DIR="${MIGRATIONS_DIR:-database/migrations}"
if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  echo "Migration directory not found: $MIGRATIONS_DIR" >&2
  exit 1
fi

DATABASE_URL="${DATABASE_URL:-}"
if [[ -z "$DATABASE_URL" ]]; then
  : "${POSTGRES_HOST:?POSTGRES_HOST is required if DATABASE_URL is not set}"
  : "${POSTGRES_DB:?POSTGRES_DB is required if DATABASE_URL is not set}"
  : "${POSTGRES_USER:?POSTGRES_USER is required if DATABASE_URL is not set}"
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required if DATABASE_URL is not set}"
  POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  export PGPASSWORD="$POSTGRES_PASSWORD"
  DATABASE_URL="postgresql://${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
fi

SCHEMA_FILE="${SCHEMA_FILE:-database/schema.sql}"
if [[ -f "$SCHEMA_FILE" ]]; then
  base_table="$(psql "$DATABASE_URL" -tA -c "SELECT to_regclass('public.financial_snapshots')" || true)"
  if [[ -z "$base_table" || "$base_table" == "null" ]]; then
    # Production sets REQUIRE_EXISTING_DB=1 after the first install: an empty
    # database there means a wrong or new volume, not a fresh install.
    if [[ "${REQUIRE_EXISTING_DB:-0}" == "1" ]]; then
      echo "refusing to create the schema on an empty database: REQUIRE_EXISTING_DB=1; restore the data first" >&2
      exit 1
    fi
    echo "Applying base schema from $SCHEMA_FILE"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"
  fi
fi

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"

mapfile -t migrations < <(find "$MIGRATIONS_DIR" -maxdepth 1 -type f -name '*.sql' | sort)
if [[ ${#migrations[@]} -eq 0 ]]; then
  echo "No migrations found in $MIGRATIONS_DIR" >&2
  exit 0
fi

for file in "${migrations[@]}"; do
  name="$(basename "$file")"
  applied="$(psql "$DATABASE_URL" -tA -c "SELECT 1 FROM schema_migrations WHERE name = '$name'")"
  if [[ "$applied" == "1" ]]; then
    echo "Skipping $name (already applied)"
    continue
  fi
  echo "Applying $name"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$file"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO schema_migrations (name) VALUES ('$name')"
done
