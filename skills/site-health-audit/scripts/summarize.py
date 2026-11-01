#!/usr/bin/env python3
"""Turn a squirrelscan JSON report into a short, prioritised site-health report.

Reads the JSON that `squirrel audit --format json` writes (schemaVersion 1.x),
ranks every finding into three tiers using priorities.json, and writes a
plain-English Markdown report (or JSON with --format json).

Optional inputs:
  --previous FILE   an earlier squirrelscan JSON for the same site: adds a
                    "Changes since last audit" section
  --crux FILE       output of crux.py: adds a "Real-user speed" section

Standard library only, so it runs on any Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PRIORITIES = HERE / "priorities.json"
RULE_DOCS = "https://docs.squirrelscan.com/rules/{rule}"
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_schema(report: dict) -> None:
    version = str(report.get("meta", {}).get("schemaVersion", ""))
    if not version.startswith("1."):
        raise SystemExit(
            f"Unsupported squirrelscan report schemaVersion {version!r}: "
            "this script understands 1.x. Re-run with a matching squirrel "
            "version or update summarize.py."
        )


def rule_tier(rule_id: str, priorities: dict) -> int:
    rules = priorities.get("rules", {})
    if rule_id in rules:
        return int(rules[rule_id])
    category = rule_id.split("/", 1)[0]
    return int(priorities.get("categoryDefaults", {}).get(category, 3))


def check_tier(rule_id: str, check: dict, base: int, priorities: dict) -> int:
    """A check's tier: the rule's tier unless a message override matches."""
    message = str(check.get("message", ""))
    for o in priorities.get("messageOverrides", []):
        if o.get("rule") == rule_id and re.search(o.get("pattern", "$^"), message, re.IGNORECASE):
            return int(o["tier"])
    return base


def tier_for(issue: dict, priorities: dict) -> int:
    """Most urgent tier across the issue's failing checks; errors are at least tier 2."""
    rule_id = issue.get("ruleId", "unknown/unknown")
    base = rule_tier(rule_id, priorities)
    checks = failing_checks(issue)
    tier = min((check_tier(rule_id, c, base, priorities) for c in checks), default=base)
    if any(c.get("status") == "fail" for c in checks) and issue.get("severity") == "error":
        tier = min(tier, 2)
    return tier


def failing_checks(issue: dict) -> list[dict]:
    return [c for c in issue.get("checks", []) if c.get("status") in ("fail", "warn")]


def pages_affected(issue: dict) -> tuple[int, bool]:
    """Largest affected-page count across the issue's failing checks."""
    best, more = 0, False
    for check in failing_checks(issue):
        count = int(check.get("affectedPagesCount") or len(check.get("affectedPages", [])))
        if count > best:
            best = count
        more = more or bool(check.get("affectedPagesHasMore"))
    return best, more


def example_pages(issue: dict, limit: int) -> list[str]:
    seen: list[str] = []
    for check in failing_checks(issue):
        for url in check.get("affectedPages", []):
            if url not in seen:
                seen.append(url)
            if len(seen) >= limit:
                return seen
    return seen


def example_items(issue: dict, limit: int) -> list[str]:
    """The things at fault (a broken URL, an oversized image), as opposed to the pages they sit on."""
    seen: list[str] = []
    for check in failing_checks(issue):
        for item in check.get("items", []) or []:
            label = str(item.get("label") or item.get("id") or "") if isinstance(item, dict) else str(item)
            if label and label not in seen:
                seen.append(label)
            if len(seen) >= limit:
                return seen
    return seen


def first_message(issue: dict) -> str:
    for check in failing_checks(issue):
        if check.get("message"):
            return str(check["message"])
    return ""


def build_findings(report: dict, priorities: dict, examples: int) -> list[dict]:
    findings = []
    for issue in report.get("issues", []):
        severity = issue.get("severity", "warning")
        if severity == "info":
            continue
        rule_id = issue.get("ruleId", "unknown/unknown")
        pages, more = pages_affected(issue)
        findings.append(
            {
                "ruleId": rule_id,
                "name": issue.get("name", rule_id),
                "category": issue.get("category", ""),
                "severity": severity,
                "tier": tier_for(issue, priorities),
                "pagesAffected": pages,
                "pagesAffectedHasMore": more,
                "summary": first_message(issue),
                "whatItMeans": issue.get("description", ""),
                "howToFix": issue.get("solution", ""),
                "exampleItems": example_items(issue, examples),
                "examplePages": example_pages(issue, examples),
                "docs": RULE_DOCS.format(rule=rule_id),
            }
        )
    # squirrelscan has overlapping rules (e.g. two for duplicate titles); keep one.
    present = {f["ruleId"] for f in findings}
    dupes = priorities.get("duplicateOf", {})
    findings = [f for f in findings if dupes.get(f["ruleId"]) not in present]
    findings.sort(
        key=lambda f: (f["tier"], SEVERITY_ORDER.get(f["severity"], 9), -f["pagesAffected"], f["ruleId"])
    )
    return findings


def coverage_notes(report: dict) -> list[str]:
    """Everything the reader must know about what this audit did NOT look at."""
    meta = report.get("meta", {})
    settings = meta.get("auditLevel", {}).get("settings", {})
    notes = []
    total, unfetched = meta.get("totalPages"), meta.get("unfetched")
    if total is not None:
        line = f"Audited {total} pages"
        if unfetched:
            line += f"; {unfetched} more known URLs were not audited (page limit {meta.get('maxPages')})"
        notes.append(line + ".")
    if report.get("status") not in (None, "completed"):
        notes.append(f"The audit status is '{report.get('status')}', so results are partial.")
    if settings.get("render") == "off":
        notes.append(
            "Pages were read as raw HTML without running JavaScript. Anything a page adds with "
            "JavaScript (some menus, forms, widgets) was not seen."
        )
    if settings.get("externalLinks") is False:
        notes.append("Links to other websites were not checked.")
    for item in report.get("notChecked", []):
        msg = item.get("message") or f"Not checked: {item.get('name', item.get('ruleId'))}."
        notes.append(msg)
    return notes


def diff_reports(current: dict, previous: dict, priorities: dict) -> dict:
    cur = {f["ruleId"]: f for f in build_findings(current, priorities, 0)}
    prev = {f["ruleId"]: f for f in build_findings(previous, priorities, 0)}
    executed = set(current.get("executedRules", []))
    not_checked = {i.get("ruleId") for i in current.get("notChecked", [])}
    warnings = []
    if current.get("meta", {}).get("baseUrl") != previous.get("meta", {}).get("baseUrl"):
        warnings.append("The two audits are of different start URLs.")
    cur_level = current.get("meta", {}).get("auditLevel", {}).get("level")
    prev_level = previous.get("meta", {}).get("auditLevel", {}).get("level")
    if cur_level != prev_level:
        warnings.append(
            f"The audits used different levels ({prev_level} then {cur_level}), so page counts are not like for like."
        )
    resolved, unknown = [], []
    for rule_id, f in prev.items():
        if rule_id in cur:
            continue
        if rule_id in not_checked or (executed and rule_id not in executed):
            unknown.append(f)
        else:
            resolved.append(f)
    changed = []
    for rule_id, f in cur.items():
        if rule_id in prev and prev[rule_id]["pagesAffected"] != f["pagesAffected"]:
            changed.append({**f, "previousPages": prev[rule_id]["pagesAffected"]})
    return {
        "previousScore": previous.get("score", {}).get("overall"),
        "previousTimestamp": previous.get("meta", {}).get("timestamp"),
        "new": [f for r, f in cur.items() if r not in prev],
        "resolved": resolved,
        "notRecheckedThisTime": unknown,
        "changed": changed,
        "warnings": warnings,
    }


def level_label(level: dict) -> str | None:
    """'full' or, when flags changed the preset, 'full (customised)'."""
    name = level.get("level")
    if name == "custom" and level.get("basedOn"):
        return f"{level['basedOn']} (customised)"
    return name


def summarize(report: dict, priorities: dict, examples: int = 3,
              previous: dict | None = None, crux: dict | None = None) -> dict:
    check_schema(report)
    meta = report.get("meta", {})
    score = report.get("score", {})
    result = {
        "site": meta.get("baseUrl"),
        "timestamp": meta.get("timestamp"),
        "level": level_label(meta.get("auditLevel", {})),
        "offline": meta.get("auditLevel", {}).get("offline"),
        "squirrelVersion": meta.get("version"),
        "score": score.get("overall"),
        "grade": score.get("grade"),
        "groups": score.get("groups", []),
        "categories": score.get("categories", []),
        "coverage": coverage_notes(report),
        "tiers": priorities.get("tiers", {}),
        "findings": build_findings(report, priorities, examples),
    }
    if previous is not None:
        check_schema(previous)
        result["diff"] = diff_reports(report, previous, priorities)
    if crux is not None:
        result["crux"] = crux
    return result


# ---------------------------------------------------------------- Markdown ---

def _pages(f: dict) -> str:
    n = f["pagesAffected"]
    if n == 0:
        return "site-level"
    return f"{n}+ pages" if f["pagesAffectedHasMore"] else f"{n} page{'s' if n != 1 else ''}"


def _host(url: str | None) -> str:
    if not url:
        return "site"
    return url.split("://", 1)[-1].rstrip("/")


def render_crux(crux: dict) -> list[str]:
    out = ["## Real-user speed (Google Chrome UX Report)", ""]
    status = crux.get("status")
    if status != "ok":
        out += [crux.get("message", f"Real-user data unavailable ({status})."), ""]
        return out
    out += [
        f"What real Chrome visitors experienced over the last 28 days "
        f"({crux.get('collectionPeriod', 'period not given')}), {crux.get('scope', 'whole site')}, "
        f"{crux.get('formFactor', 'all devices').lower()}. Google uses these three numbers as a ranking signal.",
        "",
        "| Measure | What it means | 75% of visits at or better than | Rating |",
        "|---|---|---|---|",
    ]
    for m in crux.get("metrics", []):
        out.append(f"| {m['name']} | {m['meaning']} | {m['p75Display']} | {m['rating']} |")
    out.append("")
    return out


def to_markdown(s: dict) -> str:
    host = _host(s["site"])
    date = (s.get("timestamp") or "")[:10]
    findings = s["findings"]
    by_tier = {t: [f for f in findings if f["tier"] == t] for t in (1, 2, 3)}
    tiers = s["tiers"]
    out = [
        f"# Site health: {host} ({date})",
        "",
        f"**Score: {s['score']}/100 (grade {s['grade']})** from squirrelscan {s['squirrelVersion']}, "
        f"{s['level']} level{', run offline' if s.get('offline') else ''}. "
        "Scores differ between tools; compare this number only with earlier squirrelscan runs of the same site.",
        "",
        f"**{len(by_tier[1])} to fix now, {len(by_tier[2])} to fix soon, {len(by_tier[3])} worth a look.**",
        "",
    ]
    if s.get("diff"):
        d = s["diff"]
        delta = ""
        if isinstance(d.get("previousScore"), (int, float)) and isinstance(s["score"], (int, float)):
            change = s["score"] - d["previousScore"]
            delta = f" Score {d['previousScore']} → {s['score']} ({change:+d})."
        out += [f"## Changes since the last audit ({(d.get('previousTimestamp') or '')[:10]})", ""]
        if delta:
            out += [delta.strip(), ""]
        for w in d["warnings"]:
            out.append(f"- Note: {w}")
        out.append(f"- New problems: {len(d['new'])}" + (": " + ", ".join(f["name"] for f in d["new"][:8]) if d["new"] else ""))
        out.append(f"- Resolved: {len(d['resolved'])}" + (": " + ", ".join(f["name"] for f in d["resolved"][:8]) if d["resolved"] else ""))
        if d["notRecheckedThisTime"]:
            out.append(
                f"- Not re-checked this time, so not counted as resolved: "
                + ", ".join(f["name"] for f in d["notRecheckedThisTime"][:8])
            )
        moved = [f for f in d["changed"] if f["pagesAffected"] != f["previousPages"]]
        if moved:
            out.append("- Pages affected changed: " + ", ".join(
                f"{f['name']} {f['previousPages']}→{f['pagesAffected']}" for f in moved[:8]))
        out.append("")

    for t in (1, 2):
        label = tiers.get(str(t), {}).get("label", f"Tier {t}")
        meaning = tiers.get(str(t), {}).get("meaning", "")
        out += [f"## {label} ({len(by_tier[t])})", "", meaning, ""]
        if not by_tier[t]:
            out += ["Nothing in this group.", ""]
        for i, f in enumerate(by_tier[t], 1):
            out.append(f"### {t}.{i} {f['name']} ({_pages(f)}, {f['severity']})")
            out.append("")
            if f["summary"]:
                out.append(f"**Found:** {f['summary']}")
                out.append("")
            if f["whatItMeans"]:
                out.append(f"**What it checks:** {f['whatItMeans']}")
                out.append("")
            if f["howToFix"]:
                out.append(f"**How to fix:** {f['howToFix']}")
                out.append("")
            if f["exampleItems"]:
                out.append("**At fault:** " + "; ".join(f["exampleItems"]))
                out.append("")
            if f["examplePages"]:
                out.append("**On pages such as:** " + ", ".join(f["examplePages"]))
                out.append("")
            out.append(f"Rule `{f['ruleId']}`: {f['docs']}")
            out.append("")

    label3 = tiers.get("3", {}).get("label", "Tier 3")
    out += [f"## {label3} ({len(by_tier[3])})", "", tiers.get("3", {}).get("meaning", ""), ""]
    if by_tier[3]:
        out += ["| Issue | Pages | Severity | Rule |", "|---|---|---|---|"]
        for f in by_tier[3]:
            out.append(f"| {f['name']} | {_pages(f)} | {f['severity']} | [`{f['ruleId']}`]({f['docs']}) |")
        out.append("")

    if s.get("crux"):
        out += render_crux(s["crux"])

    if s["categories"]:
        out += ["## Scores by area", "", "| Area | Score |", "|---|---|"]
        for c in sorted(s["categories"], key=lambda c: c.get("score", 100)):
            out.append(f"| {c.get('name')} | {c.get('score')} |")
        out.append("")

    out += ["## What this audit did not check", ""]
    out += [f"- {n}" for n in s["coverage"]] or ["- Nothing reported as skipped."]
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("report", help="squirrelscan JSON report")
    p.add_argument("--previous", help="earlier squirrelscan JSON for the same site")
    p.add_argument("--crux", help="JSON written by crux.py")
    p.add_argument("--priorities", default=str(DEFAULT_PRIORITIES))
    p.add_argument("--examples", type=int, default=3, help="example pages per finding (default 3)")
    p.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p.add_argument("-o", "--output", help="write here instead of stdout")
    args = p.parse_args(argv)

    s = summarize(
        load_json(args.report),
        load_json(args.priorities),
        examples=args.examples,
        previous=load_json(args.previous) if args.previous else None,
        crux=load_json(args.crux) if args.crux else None,
    )
    text = json.dumps(s, indent=2) if args.format == "json" else to_markdown(s)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
