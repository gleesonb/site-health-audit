#!/usr/bin/env python3
"""Fetch real-user Core Web Vitals for a site from Google's Chrome UX Report (CrUX) API.

The API is free (150 queries a minute per Google Cloud project) and needs an API
key with the "Chrome UX Report API" enabled. Put the key in the CRUX_API_KEY
environment variable; it is never printed or written to the output file.

Always exits 0 and writes a JSON object whose "status" is one of:
  ok             data returned
  no-data        Google has too little Chrome traffic for this site or page
  not-configured CRUX_API_KEY is not set
  error          the request failed (message says why)
so a missing key or a small site never breaks an audit run.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"

# Google's published thresholds: good <= first, poor > second.
# https://web.dev/articles/vitals
METRICS = [
    ("largest_contentful_paint", "Largest Contentful Paint (LCP)",
     "how long until the main content shows", 2500, 4000, "ms"),
    ("interaction_to_next_paint", "Interaction to Next Paint (INP)",
     "how quickly the page responds to a tap or click", 200, 500, "ms"),
    ("cumulative_layout_shift", "Cumulative Layout Shift (CLS)",
     "how much the layout jumps while loading", 0.1, 0.25, ""),
    ("first_contentful_paint", "First Contentful Paint (FCP)",
     "how long until anything shows", 1800, 3000, "ms"),
    ("experimental_time_to_first_byte", "Time to First Byte (TTFB)",
     "how long the server takes to start replying", 800, 1800, "ms"),
]


def rating(value: float, good: float, poor: float) -> str:
    if value <= good:
        return "good"
    if value <= poor:
        return "needs improvement"
    return "poor"


def display(value: float, unit: str) -> str:
    if unit == "ms":
        return f"{value / 1000:.1f} s" if value >= 1000 else f"{int(value)} ms"
    return f"{value:.2f}"


def parse_record(data: dict) -> dict:
    record = data.get("record", {})
    metrics = record.get("metrics", {})
    rows = []
    for key, name, meaning, good, poor, unit in METRICS:
        p75 = metrics.get(key, {}).get("percentiles", {}).get("p75")
        if p75 is None:
            continue
        value = float(p75)  # CLS arrives as a string
        rows.append({
            "key": key, "name": name, "meaning": meaning, "p75": value,
            "p75Display": display(value, unit), "rating": rating(value, good, poor),
        })
    period = record.get("collectionPeriod", {})

    def fmt(d: dict) -> str:
        return f"{d.get('year')}-{d.get('month', 0):02d}-{d.get('day', 0):02d}" if d else "?"

    key = record.get("key", {})
    return {
        "status": "ok",
        "scope": f"page {key['url']}" if "url" in key else f"whole site {key.get('origin', '')}",
        "formFactor": key.get("formFactor", "ALL_FORM_FACTORS").replace("_", " ").title(),
        "collectionPeriod": f"{fmt(period.get('firstDate', {}))} to {fmt(period.get('lastDate', {}))}" if period else "",
        "metrics": rows,
    }


def query(target: dict, api_key: str, timeout: float = 20.0, opener=urllib.request.urlopen) -> dict:
    body = json.dumps(target).encode()
    req = urllib.request.Request(
        f"{ENDPOINT}?key={api_key}", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with opener(req, timeout=timeout) as resp:
            return parse_record(json.loads(resp.read().decode()))
    except urllib.error.HTTPError as e:
        with e:
            return _http_error(e, target)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"status": "error", "message": f"Could not reach the CrUX API: {e}"}


def _http_error(e: urllib.error.HTTPError, target: dict) -> dict:
    if e.code == 404:
        return {"status": "no-data", "message": (
            "Google has too little real-user Chrome data for this "
            f"{'page' if 'url' in target else 'site'} to report Core Web Vitals.")}
    detail = ""
    try:
        detail = json.loads(e.read().decode()).get("error", {}).get("message", "")
    except Exception:
        pass
    return {"status": "error", "message": f"CrUX API returned HTTP {e.code}. {detail}".strip()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--origin", help="whole site, e.g. https://example.com")
    target.add_argument("--url", help="one page")
    p.add_argument("--form-factor", choices=("PHONE", "DESKTOP", "TABLET"),
                   help="limit to one device type (default: all)")
    p.add_argument("-o", "--output", help="write JSON here instead of stdout")
    args = p.parse_args(argv)

    api_key = os.environ.get("CRUX_API_KEY", "").strip()
    if not api_key:
        result = {"status": "not-configured", "message": (
            "Real-user speed data was not fetched: set CRUX_API_KEY to a Google API key with the "
            "Chrome UX Report API enabled (free). See references/crux.md.")}
    else:
        t = {"origin": args.origin.rstrip("/")} if args.origin else {"url": args.url}
        if args.form_factor:
            t["formFactor"] = args.form_factor
        result = query(t, api_key)

    text = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
