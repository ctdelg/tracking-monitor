"""Loading of the YAML configuration (markets, platforms) and repo paths."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
BASELINE_DIR = ROOT / "baseline"
RESULTS_DIR = ROOT / "results"

_yaml = YAML(typ="safe")


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return _yaml.load(fh) or {}


def load_markets(only: list[str] | None = None) -> dict:
    data = load_yaml(CONFIG_DIR / "markets.yaml")
    markets = data["markets"]
    if only:
        wanted = {m.upper() for m in only}
        markets = {k: v for k, v in markets.items() if k.upper() in wanted}
    for code, m in markets.items():
        m["code"] = code
        m.setdefault("urls", [])
        m.setdefault("journeys", [])
        m.setdefault("conversion_events", data.get("default_conversion_events", []))
    return markets


def load_settings() -> dict:
    data = load_yaml(CONFIG_DIR / "markets.yaml")
    return data.get("settings", {})


class Platforms:
    """Compiled vendor catalogue from config/platforms.yaml."""

    def __init__(self, data: dict):
        self.vendors = {}
        for vid, v in data["vendors"].items():
            self.vendors[vid] = {
                "id": vid,
                "name": v["name"],
                "severity": v.get("severity", "yellow"),
                "marketing": bool(v.get("marketing", True)),
                "patterns": [re.compile(p) for p in v["hit_patterns"]],
                "id_pattern": re.compile(v["id_pattern"]) if v.get("id_pattern") else None,
            }
        self.ignore_hosts = [re.compile(p) for p in data.get("ignore_hosts", [])]
        self.discovery_types = set(data.get("discovery_resource_types", []))
        self.click_id_cookies = data.get("click_id_cookies", {})
        self.marketing_cookies = set(data.get("marketing_cookies", []))

    def match(self, url: str) -> tuple[str, str | None] | None:
        """Return (vendor_id, account_id) if the URL is a known tracking hit."""
        for vid, v in self.vendors.items():
            if any(p.search(url) for p in v["patterns"]):
                acc = None
                if v["id_pattern"]:
                    m = v["id_pattern"].search(url)
                    acc = m.group(1) if m else None
                return vid, acc
        return None

    def is_ignored_host(self, host: str) -> bool:
        return any(p.search(host) for p in self.ignore_hosts)

    def severity(self, vendor_id: str) -> str:
        if vendor_id in self.vendors:
            return self.vendors[vendor_id]["severity"]
        # Auto-discovered vendors (other:<host>) are informational: many of them fire
        # irregularly (lazy loading, sampling), which would make markets flap to yellow.
        # Promote a vendor to yellow/red by adding it to platforms.yaml.
        return "info"

    def is_marketing(self, vendor_id: str) -> bool:
        if vendor_id in self.vendors:
            return self.vendors[vendor_id]["marketing"]
        return True  # unknown third-party hits are treated as marketing

    def display_name(self, vendor_id: str) -> str:
        if vendor_id in self.vendors:
            return self.vendors[vendor_id]["name"]
        return vendor_id


def load_platforms() -> Platforms:
    return Platforms(load_yaml(CONFIG_DIR / "platforms.yaml"))


def load_acks() -> list[dict]:
    path = CONFIG_DIR / "acks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("acks", [])
