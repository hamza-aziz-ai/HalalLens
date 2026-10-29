"""scripts/run_migrations.sh refuses an empty database when REQUIRE_EXISTING_DB=1.

Runs the real script with a fake `psql` on PATH that logs its arguments and
answers every query with nothing (as on an empty database).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(not BASH, reason="bash not available")


def _run(tmp_path, require):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "psql.log"
    psql = bin_dir / "psql"
    psql.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log.as_posix()}"\n', newline="\n")
    psql.chmod(0o755)
    (tmp_path / "migrations").mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DATABASE_URL": "postgresql://fake",
        "MIGRATIONS_DIR": (tmp_path / "migrations").as_posix(),
        "SCHEMA_FILE": (ROOT / "database/schema.sql").as_posix(),
        "REQUIRE_EXISTING_DB": require,
    }
    script = (ROOT / "scripts/run_migrations.sh").read_text().replace("\r\n", "\n")
    result = subprocess.run([BASH, "-s"], input=script, env=env, capture_output=True, text=True)
    return result, log.read_text() if log.exists() else ""


def test_require_existing_db_refuses_empty_database(tmp_path):
    result, calls = _run(tmp_path, "1")
    assert result.returncode == 1
    assert "refusing to create the schema on an empty database" in result.stderr
    assert "schema.sql" not in calls

    off = tmp_path / "off"
    off.mkdir()
    result, calls = _run(off, "0")
    assert result.returncode == 0, result.stderr
    assert "schema.sql" in calls
