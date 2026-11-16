"""Tealium utag.js: download, parse, snapshot and diff.

utag.js is public on the Tealium CDN (tags.tiqcdn.com) and not behind the
sage.com bot protection, so these checks always run fully automated.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

CDN = "https://tags.tiqcdn.com/utag/sage/{profile}/{env}/utag.js"

_TAG_RE = re.compile(r'"(\d+)":\{load:(.*?),send:(.*?),v:(\d+),wait:\d+,tid:(\d+)\}')
_RULE_RE = re.compile(r"case'(\d+)':try\{(.*?)\}catch\(e\)\{utag\.DB\(e\)\};break;")
_VERSION_RE = re.compile(r'utid:"sage/[a-z-]+/(\d{12})"')
_TEMPLATE_RE = re.compile(r"utag\.loader ut([\d.]+)")


def fetch_utag(profile: str, env: str = "prod", timeout: int = 30) -> dict:
    """Download utag.js. Returns {"url", "status", "body", "last_modified", "error"}."""
    url = CDN.format(profile=profile, env=env)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SageTrackingMonitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"url": url, "status": r.status, "body": r.read().decode("utf-8", "replace"),
                    "last_modified": r.headers.get("Last-Modified"), "error": None}
    except Exception as e:  # noqa: BLE001 - any failure is reported as evidence
        status = getattr(e, "code", None)
        return {"url": url, "status": status, "body": None, "last_modified": None, "error": str(e)}


def parse_utag(body: str) -> dict:
    """Extract version, tag configuration and load-rule source from utag.js."""
    tags = {}
    for m in _TAG_RE.finditer(body):
        tag_id, load, send, v, tid = m.groups()
        tags[tag_id] = {"load": load, "send": send, "v": v, "tid": tid}
    rules = {m.group(1): m.group(2) for m in _RULE_RE.finditer(body)}
    ver = _VERSION_RE.search(body)
    return {
        "publish_version": ver.group(1) if ver else None,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "size": len(body),
        "tags": tags,
        "load_rules": rules,
    }


def referenced_rules(expr: str) -> list[str]:
    return re.findall(r"utag\.cond\[(\d+)\]", expr)


def diff_utag(old: dict | None, new: dict, conversion_templates: set[str]) -> dict:
    """Structured diff between two parsed utag.js files.

    A change is "conversion_relevant" if it touches a tag whose template ID is in
    conversion_templates (e.g. Floodlight, Google Ads) or a load rule used by one.
    """
    if not old:
        return {"changed": False, "first_snapshot": True, "items": [], "conversion_relevant": False}
    if old["sha256"] == new["sha256"]:
        return {"changed": False, "items": [], "conversion_relevant": False}

    items = []
    conv_tags = {t for t, cfg in new["tags"].items() if cfg["tid"] in conversion_templates}
    conv_tags |= {t for t, cfg in old["tags"].items() if cfg["tid"] in conversion_templates}
    conv_rules = set()
    for t in conv_tags:
        for src in (old["tags"].get(t), new["tags"].get(t)):
            if src:
                conv_rules.update(referenced_rules(src["load"]) + referenced_rules(src["send"]))

    for t in sorted(set(old["tags"]) | set(new["tags"]), key=int):
        a, b = old["tags"].get(t), new["tags"].get(t)
        if a == b:
            continue
        if a is None:
            kind = "tag_added"
        elif b is None:
            kind = "tag_removed"
        elif a["load"] != b["load"] or a["send"] != b["send"]:
            kind = "tag_load_rule_changed"
        else:
            kind = "tag_version_changed"
        items.append({"kind": kind, "tag": t, "template": (b or a)["tid"], "before": a, "after": b,
                      "conversion_relevant": t in conv_tags and kind != "tag_version_changed"})

    for r in sorted(set(old["load_rules"]) | set(new["load_rules"]), key=int):
        a, b = old["load_rules"].get(r), new["load_rules"].get(r)
        if a == b:
            continue
        kind = "rule_added" if a is None else "rule_removed" if b is None else "rule_changed"
        items.append({"kind": kind, "rule": r, "before": a, "after": b,
                      "conversion_relevant": r in conv_rules})

    return {
        "changed": True,
        "from_version": old.get("publish_version"),
        "to_version": new.get("publish_version"),
        "items": items,
        "conversion_relevant": any(i["conversion_relevant"] for i in items),
    }


# Which vendor a Tealium tag belongs to, recognised from its utag.<id>.js file (first match wins).
TAG_SIGNATURES = [
    ("floodlight", r"fls\.doubleclick|['\"]DC-\d|floodlight"),
    ("google_ads", r"googleadservices|['\"]AW-\d|conversion_async"),
    ("microsoft_uet", r"bat\.bing|uetq"),
    ("linkedin", r"snap\.licdn|_linkedin_|lintrk"),
    ("meta", r"fbq\(|connect\.facebook\.net"),
    ("tiktok", r"ttq\.|analytics\.tiktok"),
    ("reddit", r"rdt\(|redditstatic"),
    ("quantcast", r"quantserve"),
    ("sixsense", r"6sc\.co"),
    ("openai", r"oaiq|openai"),
    ("eloqua", r"\belq|eloqua"),
    ("segment", r"segment\.com|analytics\.track"),
    ("ga4", r"['\"]G-[A-Z0-9]{6,}|gtag\("),
]
TAG_URL = "https://tags.tiqcdn.com/utag/sage/{profile}/{env}/utag.{tag}.js"


def tag_vendors(profile: str, tags: dict, wanted: set[str], cache_dir: Path, env: str = "prod") -> dict:
    """{tag id: vendor} for the wanted tag ids. utag.<id>.js is only downloaded when its version changed."""
    cache_file = cache_dir / "tag_vendors.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    out, dirty = {}, False
    for tag in wanted:
        v = (tags.get(tag) or {}).get("v")
        hit = cache.get(tag)
        if not hit or hit.get("v") != v:
            vendor = "unknown"
            try:
                req = urllib.request.Request(TAG_URL.format(profile=profile, env=env, tag=tag),
                                             headers={"User-Agent": "SageTrackingMonitor/1.0"})
                js = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
                vendor = next((name for name, rx in TAG_SIGNATURES if re.search(rx, js)), "other")
            except Exception:  # noqa: BLE001 - keep "unknown", retry next run
                pass
            hit = {"v": v, "vendor": vendor}
            if vendor != "unknown":
                cache[tag], dirty = hit, True
        out[tag] = hit["vendor"]
    if dirty:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    return out


def save_snapshot(directory: Path, day: str, body: str, parsed: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{day}.js").write_text(body, encoding="utf-8")
    (directory / f"{day}.json").write_text(json.dumps(parsed, indent=1), encoding="utf-8")


def latest_snapshot(directory: Path, before_day: str) -> dict | None:
    if not directory.exists():
        return None
    days = sorted(p.stem for p in directory.glob("*.json") if p.stem < before_day)
    if not days:
        return None
    return json.loads((directory / f"{days[-1]}.json").read_text(encoding="utf-8"))
