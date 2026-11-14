"""Dashboard / report rendering.

Two outputs from one template:
  - write_dashboard(): page content for the Claude artifact (the artifact skeleton adds
    <html>/<head>), with live acknowledgements through the artifact database.
  - write_static(): standalone report/index.html (fallback, e.g. GitHub Pages / Actions artifact),
    same layout, acknowledgements read-only from config/acks.json.

Both embed the day's results, the Claude diagnosis (if present) and the full history index.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import RESULTS_DIR, ROOT, load_acks

TEMPLATE = Path(__file__).parent / "dashboard_template.html"


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _trim(doc: dict) -> dict:
    """Keep evidence only where it explains a finding; passes carry no evidence."""
    for m in doc.get("markets", {}).values():
        for c in m.get("checks", []):
            if c["result"] == "pass":
                c["evidence"] = {}
        diff = (m.get("utag") or {}).get("diff") or {}
        for item in diff.get("items", []):
            for k in ("before", "after"):
                if isinstance(item.get(k), str) and len(item[k]) > 600:
                    item[k] = item[k][:600] + " …"
    return doc


def build_payload(day: str) -> dict:
    doc = _read(RESULTS_DIR / f"{day}.json")
    if not doc:
        days = sorted(p.stem for p in RESULTS_DIR.glob("????-??-??.json"))
        if not days:
            raise SystemExit("No results yet. Run: python -m monitor run")
        doc = _read(RESULTS_DIR / f"{days[-1]}.json")
    return {
        "results": _trim(doc),
        "diagnosis": _read(RESULTS_DIR / "diagnosis" / f"{doc['day']}.json"),
        "history": _read(RESULTS_DIR / "index.json", {"days": {}}),
        "acks_file": load_acks(),
    }


def _render(day: str, mode: str) -> str:
    payload = build_payload(day)
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    return html.replace("__MODE__", mode).replace("__DATA__", data)


def write_dashboard(day: str, out: str) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(day, "artifact"), encoding="utf-8")
    return path


def write_static(day: str) -> Path:
    body = _render(day, "static")
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "</head><body>" + body + "</body></html>")
    path = ROOT / "report" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
