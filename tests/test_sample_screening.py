"""The landing page's sample screening must be exactly what the engine produces."""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sample = runpy.run_path(str(ROOT / "scripts" / "sample_screening.py"))


def test_committed_sample_matches_engine():
    committed = (ROOT / "ui" / "lib" / "sample-screening.json").read_text(encoding="utf-8")
    assert committed == sample["render"](), "run: python scripts/sample_screening.py"


def test_sample_shows_one_pass_and_one_fail():
    verdicts = [c["verdict"] for c in json.loads(sample["render"]())["companies"]]
    assert verdicts == ["compliant", "non-compliant"]
