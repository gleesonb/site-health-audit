#!/usr/bin/env python3
"""Audit one or more websites with squirrelscan, offline, and write prioritised reports.

For each site it:
  1. runs `squirrel audit <url> --offline --format json` (never signed in, never
     published, no credits, no telemetry);
  2. fetches real-user Core Web Vitals with crux.py if CRUX_API_KEY is set;
  3. writes a Markdown report with summarize.py, compared with the newest
     earlier audit of the same site at the same level, if there is one.

Output layout:  <out>/<host>/<YYYY-MM-DD>-<level>.{json,crux.json,md}

Sites come from the command line or from --sites FILE, one per line:
    https://example.com                      # level from --level
    https://club.example.org level=full passive max-pages=300
Blank lines and lines starting with # are ignored.

Exit status: 0 if every site was audited, 1 if any failed (each failure is
listed with squirrelscan's reason).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import crux  # noqa: E402
import summarize  # noqa: E402

LEVELS = ("quick", "surface", "full")
# squirrelscan exit codes that mean nothing was audited.
EXIT_REASONS = {
    3: "blocked: the site refused the crawler (check robots.txt or a firewall/bot wall)",
    4: "redirected: the start URL sends visitors to another site; audit the destination instead",
    5: "unreachable: DNS, TLS or connection failure",
}


def parse_sites_file(text: str, default_level: str) -> list[dict]:
    sites = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        url, *opts = line.split()
        site = {"url": url, "level": default_level, "passive": False, "maxPages": None}
        for opt in opts:
            if opt == "passive":
                site["passive"] = True
            elif opt.startswith("level="):
                site["level"] = opt.split("=", 1)[1]
            elif opt.startswith("max-pages="):
                site["maxPages"] = int(opt.split("=", 1)[1])
            else:
                raise SystemExit(f"sites file line {n}: unknown option {opt!r}")
        sites.append(site)
    return sites


def validate(site: dict) -> None:
    u = urlparse(site["url"])
    if u.scheme not in ("http", "https") or not u.netloc:
        raise SystemExit(f"Not a website URL: {site['url']!r} (include https://)")
    if site["level"] not in LEVELS:
        raise SystemExit(f"Unknown level {site['level']!r} for {site['url']}; use one of {', '.join(LEVELS)}")


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def previous_audit(site_dir: Path, level: str, exclude: Path) -> Path | None:
    # Newest by modification time: same-day reruns get a time in the name that
    # does not sort after the plain date, so names cannot be trusted for order.
    candidates = sorted(
        (p for p in site_dir.glob(f"*-{level}.json") if p != exclude and not p.name.endswith(".crux.json")),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def squirrel_command(squirrel: str, site: dict, out_json: Path) -> list[str]:
    cmd = [squirrel, "audit", site["url"], "--offline", "--level", site["level"],
           "--format", "json", "-o", str(out_json), "-y"]
    if site["passive"]:
        cmd.append("--passive")
    if site["maxPages"]:
        cmd += ["--max-pages", str(site["maxPages"])]
    return cmd


def audit_one(site: dict, out_root: Path, squirrel: str, today: str, examples: int) -> dict:
    host = host_of(site["url"])
    site_dir = out_root / host
    site_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{today}-{site['level']}"
    out_json = site_dir / f"{stem}.json"
    if out_json.exists():  # second run on the same day keeps both
        stem = f"{today}-{dt.datetime.now().strftime('%H%M%S')}-{site['level']}"
        out_json = site_dir / f"{stem}.json"
    prev = previous_audit(site_dir, site["level"], out_json)

    env = {**os.environ, "DO_NOT_TRACK": "1", "NO_TELEMETRY": "1"}
    proc = subprocess.run(squirrel_command(squirrel, site, out_json), env=env,
                          capture_output=True, text=True)
    if proc.returncode not in (0, 2) or not out_json.exists():
        reason = EXIT_REASONS.get(proc.returncode, f"squirrel exited with status {proc.returncode}")
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        return {"host": host, "ok": False, "reason": reason, "detail": " | ".join(tail)}

    crux_path = None
    if os.environ.get("CRUX_API_KEY", "").strip():
        origin = f"{urlparse(site['url']).scheme}://{urlparse(site['url']).netloc}"
        crux_path = site_dir / f"{stem}.crux.json"
        crux.main(["--origin", origin, "-o", str(crux_path)])

    report = summarize.load_json(out_json)
    s = summarize.summarize(
        report,
        summarize.load_json(summarize.DEFAULT_PRIORITIES),
        examples=examples,
        previous=summarize.load_json(prev) if prev else None,
        crux=summarize.load_json(crux_path) if crux_path else None,
    )
    md_path = site_dir / f"{stem}.md"
    md_path.write_text(summarize.to_markdown(s) + "\n", encoding="utf-8")
    counts = {t: sum(1 for f in s["findings"] if f["tier"] == t) for t in (1, 2, 3)}
    return {
        "host": host, "ok": True, "score": s["score"], "grade": s["grade"], "pages": report.get("meta", {}).get("totalPages"),
        "counts": counts, "report": str(md_path), "json": str(out_json),
        "previous": str(prev) if prev else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("urls", nargs="*", help="site URLs (https://...)")
    p.add_argument("--sites", help="file listing sites, one per line")
    p.add_argument("--level", choices=LEVELS, default="surface",
                   help="quick = 25 pages, surface = 100 (default), full = 500")
    p.add_argument("--passive", action="store_true",
                   help="no security probe requests (use for sites you do not run yourself)")
    p.add_argument("--out", default="site-audits", help="output folder (default ./site-audits)")
    p.add_argument("--examples", type=int, default=3)
    p.add_argument("--squirrel", default="squirrel", help="path to the squirrel binary")
    args = p.parse_args(argv)

    sites = [{"url": u, "level": args.level, "passive": args.passive, "maxPages": None} for u in args.urls]
    if args.sites:
        sites += parse_sites_file(Path(args.sites).read_text(encoding="utf-8"), args.level)
    if not sites:
        p.error("give at least one URL or --sites FILE")
    for s in sites:
        validate(s)

    today = dt.date.today().isoformat()
    results = []
    for i, site in enumerate(sites, 1):
        print(f"[{i}/{len(sites)}] auditing {site['url']} ({site['level']})...", file=sys.stderr, flush=True)
        results.append(audit_one(site, Path(args.out), args.squirrel, today, args.examples))

    ok = [r for r in results if r["ok"]]
    print(f"\nAudited {len(ok)} of {len(results)} sites.")
    for r in results:
        if r["ok"]:
            c = r["counts"]
            print(f"- {r['host']}: {r['score']}/100 ({r['grade']}), {r['pages']} pages; "
                  f"{c[1]} fix now, {c[2]} fix soon, {c[3]} worth a look -> {r['report']}")
        else:
            print(f"- {r['host']}: NOT AUDITED, {r['reason']}. {r['detail']}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
