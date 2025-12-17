FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock /app/

RUN pip install --no-cache-dir pipenv==2023.3.20 \
 && PIPENV_VENV_IN_PROJECT=1 pipenv install --system --deploy

COPY . /app

CMD ["python", "-m", "jobs.ingestion_cycle", "--lookback-days", "1"]
