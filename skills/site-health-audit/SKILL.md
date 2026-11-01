---
name: site-health-audit
description: Run a Semrush-style technical SEO and site-health audit of one or more websites from the command line, for free, and explain the results in plain English, ranked by what to fix first. Crawls with the squirrelscan CLI in offline mode (300+ rules - indexability, broken links, redirects, titles, canonicals, sitemaps, HTTPS, speed, structured data, accessibility), adds Google's real-user Core Web Vitals when a CrUX key is set, and compares each run with the last one. Use when the user asks to audit, health-check or SEO-check a website, asks "what's wrong with my site", wants a site audit like Semrush, Ahrefs or Screaming Frog, or wants to re-check sites they manage.
license: MIT
compatibility: Needs the squirrel CLI (squirrelscan) on PATH and Python 3.10+. Linux, macOS or WSL.
allowed-tools: Bash(squirrel:*) Bash(python3:*) Read Grep Glob
metadata:
  version: "0.1.0"
---

# Site health audit

Audit websites with squirrelscan, running locally and offline, and turn its long rule-by-rule output into a short report a site owner without SEO knowledge can act on: what to fix now, what to fix soon, what can wait, and what the audit did not check.

<critical>
1. Run every audit through `scripts/audit_sites.py`, which always passes `--offline`. Do not run `squirrel auth login`, pass `--publish`, or use the squirrelscan cloud MCP tools (`run_audit` and friends): signed-in and cloud audits spend credits, publish an unlisted report, and switch on recurring audits by themselves.
2. Pass `--passive` for any site the user does not run themselves, and never use `--aggressive` or `--pentest`: those send probe requests that look like an attack and can get the user's IP blocked.
3. A check that was skipped is not a pass. Always tell the user what the audit did not check (the report's last section), and never call an issue resolved unless the newer audit actually re-checked it.
4. Do not change the live site. Propose fixes and wait for the user to approve each batch; most sites in scope are production marketing sites.
5. Compare a score only with earlier squirrelscan runs of the same site at the same level. Semrush, Ahrefs and squirrelscan calculate scores differently.
</critical>

## Before the first audit

1. Check the CLI: `squirrel --version`. If it is missing, tell the user it installs as a single binary from https://docs.squirrelscan.com/agent-setup and that the installer should be downloaded and read before it is run, not piped into a shell unseen. Do not sign in afterwards.
2. Get the site URL(s). If the user did not say, ask. Ask whether they run each site; if not, it gets `--passive`.
3. Pick a level. `quick` = 25 pages, a first look in under a minute. `surface` = 100 pages sampled one per URL pattern, the default. `full` = up to 500 pages, for a complete picture or before sign-off.

## Run the audit

```bash
python3 scripts/audit_sites.py https://example.com --level surface --out site-audits
python3 scripts/audit_sites.py --sites sites.txt --out site-audits     # several sites
```

`scripts/` is relative to this skill's directory. A sites file has one site per line, with optional `level=quick|surface|full`, `passive` and `max-pages=N`; `#` starts a comment.

Each site gets `site-audits/<host>/<date>-<level>.json` (squirrelscan's full report) and `<date>-<level>.md` (the prioritised report). When an earlier audit of the same site at the same level exists in that folder, the report gains a "Changes since the last audit" section automatically. A full audit takes a few minutes; run it in the background if your harness allows.

If `CRUX_API_KEY` is set, the report also gets a "Real-user speed" section from Google's Chrome UX Report. Without it, say once that real-user speed was not checked and point to `references/crux.md`; do not ask for the key mid-task.

The script prints `Audited N of M sites` and one line per site. A site marked NOT AUDITED has a reason: blocked (robots.txt or a bot wall), redirected (audit the destination URL instead) or unreachable. Report those; do not retry more than once.

## Present the results

Read the generated `.md` file, then give the user, in this order:

1. The score and grade, and the counts: N fix now, N fix soon, N worth a look.
2. Each "Fix now" item in one or two plain sentences: what is wrong, how many pages, and what the fix involves. Translate jargon (canonical, noindex, LCP) the first time it appears.
3. The three to five "Fix soon" items that affect the most pages.
4. What was not checked, in one line, e.g. "links to other sites and pages that need JavaScript were not checked".
5. The report path, so they can read the rest.

Do not paste the whole report into the chat. Do not re-rank findings by your own judgement; the tiers come from `scripts/priorities.json` so that runs are consistent. If a tier looks wrong for this site (for example hreflang on a single-language site), say so and suggest editing `priorities.json`.

## Going deeper

- One finding in full: look it up in the JSON (`issues[]` where `ruleId` matches); every finding has its rule's documentation link in the report.
- All findings in one category, compact: `squirrel report -i <file>.json --format llm --category <name>`.
- Why a rule sits in its tier: `references/priorities.md`.
- Re-render without re-crawling: `python3 scripts/summarize.py <file>.json [--previous <older>.json] [--crux <file>.crux.json]`.

## Fixing

If the user wants fixes and the site's source is in front of you (a repo, a theme), propose one batch at a time, starting with "Fix now", and wait for approval. squirrelscan's own `audit-website` skill has a fix loop for code you control. For a CMS such as WordPress, explain where in the admin the fix lives instead of editing files. After a deploy, re-run the same level with the same `--out` folder so the diff shows what changed.

## Limits to state when relevant

- Offline mode reads raw HTML and does not run JavaScript, so it under-reports on sites built mostly in JavaScript.
- External links are not checked offline.
- Google's own view of which pages it has indexed lives in Google Search Console, which this skill does not read.

<critical>
1. Run every audit through `scripts/audit_sites.py`, which always passes `--offline`. Do not run `squirrel auth login`, pass `--publish`, or use the squirrelscan cloud MCP tools (`run_audit` and friends): signed-in and cloud audits spend credits, publish an unlisted report, and switch on recurring audits by themselves.
2. Pass `--passive` for any site the user does not run themselves, and never use `--aggressive` or `--pentest`: those send probe requests that look like an attack and can get the user's IP blocked.
3. A check that was skipped is not a pass. Always tell the user what the audit did not check (the report's last section), and never call an issue resolved unless the newer audit actually re-checked it.
4. Do not change the live site. Propose fixes and wait for the user to approve each batch; most sites in scope are production marketing sites.
5. Compare a score only with earlier squirrelscan runs of the same site at the same level. Semrush, Ahrefs and squirrelscan calculate scores differently.
</critical>
