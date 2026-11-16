"""Lead form checks (demo, product tour, download, quote, contact ...).

sage.com lead forms are "gates" from Gated Content (app.gatedcontent.com). A CTA such as
"Produkttour starten" links to #gate-<id>; the gate opens a form. On a successful submit the
account-wide event script calls

    utag.link({event: "form", action: "form_submit_success",
               gate_content_name: <gate.lastContentName>, gate_campaign_id: <gate.sfdcCampaignID>, ...})

and Tealium derives the lead type from codes inside gate_content_name (_TOO_/_DEM_/_TRL_ ->
trial_demo, _CON_/_QUO_ -> contact, _PDF_/_BRO_ -> download ...) to decide which Floodlight /
Ads conversion tags fire.

Everything needed is public and outside the sage.com bot protection:
  - the gate configuration:   app.gatedcontent.com/gates/<account>/<gate id>
  - the event script:         app.gatedcontent.com/components/events/<account>/get/live/events
  - the Tealium rules:        tags.tiqcdn.com (see loadrules.py)
So the monitor rebuilds the exact submit event for every form and replays it through Tealium,
without ever submitting a form.

Which gates sit on which page is discovered by a browser visit (collector.js `gates`) and kept
in config/forms/<MKT>.json, so the daily check runs even while page visits are blocked.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from .config import CONFIG_DIR

API = "https://app.gatedcontent.com"
FORMS_DIR = CONFIG_DIR / "forms"

# Fields the live event script must send for conversion tracking to work (FORM-00).
REQUIRED_SCRIPT_PARTS = {
    "utag.link": r"utag\.link\(",
    "action=form_submit_success": r"action\s*=\s*\"form_submit_success\"",
    "gate_content_name=lastContentName": r"gate_content_name\s*=\s*gcdc\.getValue\(\"gateAttribute\.lastContentName\"\)",
}

# Lead type codes Tealium reads from gate_content_name (extension on all EU profiles).
LEAD_CODES = {
    "download": "ART|CHK|DSH|GDE|IMG|INF|PDF|BRO|TGD|TMP|VID|YTB",
    "application": "EVE|EVA|EVC|SUB|RES|WEB|WBA|WBC",
    "contact": "BNT|TLM|RCS|ADD|CON|QUO|EML",
    "trial_demo": "DEM|TRL|TOOL|DEMO|TOO",
    "purchase": "PUR",
}
NAME_CONVENTION = re.compile(r"^[A-Z]+_[A-Z0-9]+_[A-Z]{2}_[A-Z]+_[A-Z]+_")


def _get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SageTrackingMonitor/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_event_script(account: str) -> dict:
    try:
        body = _get_json(f"{API}/components/events/{account}/get/live/events")["Body"]["events"]
        script = body.get("form", {}).get("submissionSucceed", "")
        missing = [k for k, rx in REQUIRED_SCRIPT_PARTS.items() if not re.search(rx, script)]
        return {"ok": True, "missing": missing, "script_len": len(script)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}


def fetch_gate(account: str, gate_id: str) -> dict:
    try:
        b = _get_json(f"{API}/gates/{account}/{gate_id}")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
    if b.get("Error") or not b.get("Body"):
        return {"ok": False, "error": b.get("Message") or "empty response"}
    g = b["Body"]
    u = lambda k: unquote(str(g.get(k) or ""))  # noqa: E731
    return {
        "ok": True,
        "gate_id": gate_id,
        "gate_name": u("gateName"),
        "gate_type": u("gateType"),                 # general | redirect | download | chilipiper | webinar ...
        "form_type": u("formType"),
        "last_content_name": u("lastContentName"),
        "campaign_id": u("sfdcCampaignID"),
        "score": u("gateScoringValue"),
        "product": u("defaultProduct"),
        "redirect_url": u("redirectUrl"),
        "download_url": u("downloadUrl"),
        "inactive": u("gateInactive").lower() in ("true", "1", "yes"),
        "schedule_active": u("gateScheduleActive").lower() in ("true", "1", "yes"),
        "schedule_end": u("gateScheduleEndDatetime"),
        "updated_at": u("updated_at"),
    }


def lead_type(content_name: str) -> str | None:
    if not content_name:
        return None
    if re.search(r".{3}_(OT|OTH)_|gateid_not_set", content_name, re.I):
        return "other"
    for kind, codes in LEAD_CODES.items():
        if re.search(rf"_({codes})_", content_name, re.I):
            return kind
    return None


def submit_payload(gate: dict) -> dict:
    """The utag.link payload the live event script would send for this gate."""
    return {
        "event": "form", "action": "form_submit_success", "event_type": "submit",
        "triggered_by": "gated_content",
        "gate_content_name": gate["last_content_name"],
        "gate_campaign_id": gate["campaign_id"],
        "gate_score": gate["score"],
        "modal_gate": gate["gate_id"],
        "item_name": gate["product"],
        "form_step": 1, "step_name": "step_1", "total_steps": 1,
        # Typical form answers (some Floodlight tags only fire for >4 employees).
        "number_of_employees": "10-49 Employees",
        "industry": "Professional Services",
    }


# ---------------------------------------------------------------------------------------
# Inventory: which gates sit on which page
# ---------------------------------------------------------------------------------------

def inventory_path(market: str) -> Path:
    return FORMS_DIR / f"{market}.json"


def load_inventory(market: str) -> dict:
    p = inventory_path(market)
    if not p.exists():
        return {"market": market, "pages": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def update_inventory(market: str, page_id: str, gates: list[dict], day: str | None = None) -> None:
    """gates: [{"id": gate_id, "ctas": ["Demo anfordern", ...], "rendered": bool}] from collector.js."""
    inv = load_inventory(market)
    inv["pages"][page_id] = {"discovered": day or date.today().isoformat(), "gates": gates}
    FORMS_DIR.mkdir(parents=True, exist_ok=True)
    inventory_path(market).write_text(json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8")


def gates_in_inventory(inv: dict) -> dict:
    """{gate_id: {"pages": [...], "ctas": [...], "rendered_everywhere": bool}}"""
    out: dict[str, dict] = {}
    for page_id, p in inv.get("pages", {}).items():
        for g in p.get("gates", []):
            e = out.setdefault(g["id"], {"pages": [], "ctas": set()})
            e["pages"].append(page_id)
            e["ctas"].update(g.get("ctas", []))
            # Modal gates are injected by Gated Content when the CTA is clicked, so a gate that is
            # not rendered on load is normal. A dead CTA shows up as FORM-01 (config missing/inactive).
            for k in ("target_status", "target_url"):
                if g.get(k) is not None:
                    e[k] = g[k]
    for e in out.values():
        e["ctas"] = sorted(e["ctas"])
    return out


def collect(market: dict, account: str) -> dict:
    """Fetch every inventoried gate's config. Returns the 'forms' part of the raw evidence."""
    inv = load_inventory(market["code"])
    gates = gates_in_inventory(inv)
    fetched = {gid: {**fetch_gate(account, gid), **meta} for gid, meta in gates.items()}
    return {"event_script": fetch_event_script(account), "gates": fetched,
            "inventory_pages": sorted(inv.get("pages", {}))}
