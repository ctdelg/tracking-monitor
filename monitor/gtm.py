"""Google Tag Manager containers (sites that do not use Tealium, e.g. sagedpw.at for AT).

The published container is public: https://www.googletagmanager.com/gtm.js?id=GTM-XXXX
It embeds the container definition as JSON ("resource": {version, tags, ...}). The monitor
keeps a daily snapshot of the tag list and reports publishes and conversion-tag changes,
the same way it does for Tealium's utag.js.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

URL = "https://www.googletagmanager.com/gtm.js?id={container}"

# GTM template ids that matter for paid media.
CONVERSION_FUNCTIONS = {"__flc": "Floodlight counter", "__fls": "Floodlight sales", "__awct": "Google Ads conversion",
                        "__sp": "Google Ads remarketing", "__gclidw": "Conversion Linker", "__cl": "Conversion Linker",
                        "__baut": "Microsoft UET", "__bzi": "LinkedIn Insight"}
ID_FIELDS = ("vtp_advertiserId", "vtp_groupTag", "vtp_activityTag", "vtp_conversionId", "vtp_conversionLabel",
             "vtp_tagId", "vtp_measurementId", "vtp_partnerId", "vtp_pixelId", "vtp_uetqTagId")


def fetch(container: str, timeout: int = 30) -> dict:
    url = URL.format(container=container)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SageTrackingMonitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"url": url, "status": r.status, "body": r.read().decode("utf-8", "replace"), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": getattr(e, "code", None), "body": None, "error": str(e)[:300]}


def _resource(js: str) -> dict:
    i = js.find('"resource":')
    start = js.find("{", i)
    depth, in_str, esc = 0, False, False
    for k in range(start, len(js)):
        ch = js[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(js[start:k + 1])
    raise ValueError("container resource not found")


def _triggers(res: dict) -> dict:
    """{activity or tag label: [[condition, ...], ...]} for live Floodlight tags (one list per firing trigger).

    Trigger groups (__tg) are resolved to their member triggers; each condition is
    {"fn": "_cn"/"_eq"/"_re"..., "var": "ID"/"URL"/"Event"..., "value": "..."}.
    """
    tags, preds, macros = res.get("tags", []), res.get("predicates", []), res.get("macros", [])

    def var(ref):
        if isinstance(ref, list) and ref and ref[0] == "macro":
            m = macros[ref[1]]
            return m.get("vtp_name") or m.get("vtp_varType") or m.get("function")
        return ref

    def conds(rule, key):
        return [{"fn": preds[i]["function"], "var": var(preds[i].get("arg0")), "value": preds[i].get("arg1")}
                for part in rule if part[0] == key for i in part[1:]]

    by_tag: dict[int, list] = {}
    for rule in res.get("rules", []):
        for part in rule:
            if part[0] == "add":
                for t in part[1:]:
                    by_tag.setdefault(t, []).append(conds(rule, "if"))
    firing = {t.get("vtp_firingId"): i for i, t in enumerate(tags) if t.get("function") == "__tg" and t.get("vtp_firingId")}
    groups = {t.get("vtp_uniqueTriggerId"): t.get("vtp_triggerIds", [])[1:] for t in tags
              if t.get("function") == "__tg" and t.get("vtp_uniqueTriggerId")}
    out = {}
    for i, t in enumerate(tags):
        if t.get("function") not in ("__flc", "__fls", "__awct"):
            continue
        label = t.get("vtp_activityTag") or t.get("vtp_conversionLabel") or str(t.get("tag_id"))
        paths = []
        for cs in by_tag.get(i, []):
            gid = next((str(c["value"]) for c in cs if c["var"] == "gtm.triggers"), None)
            members = []
            if gid:
                m = re.search(r"\d+_\d+", gid)
                for fid in groups.get(m.group(0), []) if m else []:
                    members += [c for cc in by_tag.get(firing.get(fid), []) for c in cc]
            paths.append([c for c in cs if c["var"] not in ("gtm.triggers",) and c["value"] != "gtm.triggerGroup"] + members)
        out[label] = paths
    return out


def parse(js: str) -> dict:
    res = _resource(js)
    tags = {}
    for t in res.get("tags", []):
        ids = {k[4:]: t[k] for k in ID_FIELDS if isinstance(t.get(k), str)}
        fn = t.get("function")
        if fn == "__paused":
            fn = "__paused:" + str(t.get("vtp_originalTagType"))
        tags[str(t.get("tag_id"))] = {"function": fn, "ids": ids}
    return {"version": str(res.get("version")), "sha256": hashlib.sha256(js.encode("utf-8")).hexdigest(), "tags": tags,
            "triggers": _triggers(res)}


def conversion_tags(parsed: dict) -> dict:
    """{tag id: label} for Floodlight / Ads / UET / LinkedIn tags that are live (not paused)."""
    out = {}
    for tid, t in parsed["tags"].items():
        if t["function"] in CONVERSION_FUNCTIONS:
            ids = t["ids"]
            label = CONVERSION_FUNCTIONS[t["function"]]
            detail = "/".join(filter(None, [ids.get("advertiserId"), ids.get("groupTag"), ids.get("activityTag"),
                                            ids.get("conversionId"), ids.get("conversionLabel")]))
            out[tid] = f"{label} {detail}".strip()
    return out


def diff(old: dict | None, new: dict) -> dict:
    if not old:
        return {"changed": False, "first_snapshot": True, "items": [], "conversion_relevant": False}
    if old["sha256"] == new["sha256"]:
        return {"changed": False, "items": [], "conversion_relevant": False}
    items = []
    for tid in sorted(set(old["tags"]) | set(new["tags"]), key=lambda x: int(x) if x.isdigit() else 0):
        a, b = old["tags"].get(tid), new["tags"].get(tid)
        if a == b:
            continue
        kind = "tag_added" if a is None else "tag_removed" if b is None else "tag_changed"
        fns = {(a or {}).get("function"), (b or {}).get("function")}
        items.append({"kind": kind, "tag": tid, "before": a, "after": b,
                      "conversion_relevant": bool(fns & set(CONVERSION_FUNCTIONS))
                      or any(str(f).startswith("__paused") for f in fns if f)})
    return {"changed": True, "from_version": old.get("version"), "to_version": new.get("version"),
            "items": items, "conversion_relevant": any(i["conversion_relevant"] for i in items)}


def latest_snapshot(directory: Path, before_day: str) -> dict | None:
    if not directory.exists():
        return None
    days = sorted(p.stem for p in directory.glob("*.json") if p.stem < before_day)
    return json.loads((directory / f"{days[-1]}.json").read_text(encoding="utf-8")) if days else None


def save_snapshot(directory: Path, day: str, parsed: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{day}.json").write_text(json.dumps(parsed, indent=1), encoding="utf-8")
