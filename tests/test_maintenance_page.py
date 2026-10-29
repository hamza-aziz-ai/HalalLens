"""The Cloudflare Worker serves the same maintenance page as the front Caddy."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_worker_embeds_the_caddy_maintenance_page_verbatim():
    page = (ROOT / "caddy/maintenance.html").read_text(encoding="utf-8").replace("\r\n", "\n")
    worker = (ROOT / "cloudflare/maintenance-worker.js").read_text(encoding="utf-8").replace("\r\n", "\n")
    embedded = re.search(r"const PAGE = `(.*?)`;", worker, re.S)
    assert embedded and embedded.group(1) == page, "copy caddy/maintenance.html into the Worker's PAGE"


def test_page_is_self_contained():
    # Nothing else is reachable while the site is down: no external assets.
    page = (ROOT / "caddy/maintenance.html").read_text(encoding="utf-8")
    assert not re.search(r"""(src|href)=["']?https?:""", page)
