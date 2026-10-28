# One image for every Python role: the API (default command), preflight,
# migrations and the ingestion/evaluation schedulers (compose sets their
# commands).
#
# Must match [requires] python_version in Pipfile: `pipenv install --deploy`
# aborts when the interpreter does not match the locked version.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Kolkata

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# psql runs the migrations (scripts/run_migrations.sh). No compiler or libpq
# headers: every locked package installs from a prebuilt wheel on amd64 and
# arm64 (psycopg2-binary bundles libpq).
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
 && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock /app/

# PIP_ONLY_BINARY: fail the build instead of silently compiling from source.
RUN pip install --no-cache-dir "pipenv>=2024.4.0" \
 && PIP_ONLY_BINARY=:all: pipenv install --system --deploy \
 && pip uninstall -y pipenv virtualenv

COPY . /app
# Shell scripts from a Windows checkout (core.autocrlf) arrive with CRLF and
# fail under bash (migrations run scripts/run_migrations.sh in this image).
RUN find /app/scripts -name '*.sh' -exec sed -i 's/\r$//' {} +

# Runs unprivileged. The app writes only to these directories (and /tmp for
# heartbeats); named volumes mounted on them take this ownership when first
# created. A volume created by an older, root-run image keeps root ownership:
# fix it once with `chown -R 10001:10001` (see README_ops.md).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin halallens \
 && mkdir -p cache downloads logs logs_runtime \
 && chown -R halallens:halallens cache downloads logs logs_runtime
USER 10001:10001

ARG POSTGRES_HOST=postgres
ENV POSTGRES_HOST=${POSTGRES_HOST}

EXPOSE 8001

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8001"]
