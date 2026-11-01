# site-health-audit

A Claude Code skill that audits websites the way the free Semrush Site Audit does, for nothing, from the command line, and explains the results in plain English for people who are not SEO specialists.

It crawls with [squirrelscan](https://github.com/squirrelscan/squirrelscan) in offline mode (about 280 rules: indexability, broken links, redirects, titles, canonicals, sitemaps, HTTPS, speed, structured data, accessibility), then:

- **ranks every finding** into *Fix now*, *Fix soon* and *Worth a look*, using a priority map tuned for small marketing, SaaS and club sites ([why each rule sits where it does](skills/site-health-audit/references/priorities.md));
- **says what it did not check**: pages beyond the limit, JavaScript-only content, external links, so a skipped check is never mistaken for a pass;
- **adds Google's real-user Core Web Vitals** from the Chrome UX Report when you give it a free API key;
- **compares each run with the last one**: new problems, resolved ones, and ones the newer run could not re-check;
- **audits several sites in one go** from a simple sites file.

## Why not just use squirrelscan's own skill?

squirrelscan's `audit-website` skill is a developer fix loop: audit, edit the code, re-audit. This one is for the site owner who needs to know what matters first. For a 100-page site, squirrelscan's Markdown report runs to thousands of lines; this skill's report is a few pages, ordered by business impact. It also locks in safe defaults: every audit runs `--offline`, so nothing is published, no credits are spent and no recurring cloud audits get switched on. Use both: this skill to decide what to fix, squirrelscan's to fix it in code.

## Install

1. Install the squirrel CLI (a single binary). Download the installer and read it before running it:
   ```bash
   curl -fsSL https://install.squirrelscan.com/install.sh -o install.sh
   less install.sh && bash install.sh
   squirrel self doctor
   ```
   You do not need to sign in.
2. Add the skill to Claude Code:
   ```
   /plugin marketplace add gleesonb/site-health-audit
   /plugin install site-health-audit@site-health-audit
   ```
   Or copy `skills/site-health-audit/` into `~/.claude/skills/`.
3. Optional: set `CRUX_API_KEY` for real-user speed data ([how](skills/site-health-audit/references/crux.md)).

Python 3.10+ is the only other requirement; the scripts use the standard library.

## Use

Ask Claude: *"audit example.com"*, *"run a full site audit of my sites"*, *"what changed on example.com since last month?"*

Or run the scripts directly:

```bash
S=skills/site-health-audit/scripts
python3 $S/audit_sites.py https://example.com --level surface        # 100 pages
python3 $S/audit_sites.py --sites sites.txt --out site-audits          # several sites
python3 $S/summarize.py site-audits/example.com/2026-11-01-full.json   # re-render a report
```

`sites.txt`:
```
https://example.com                         level=full
https://partner-site.example passive        # a site you do not run: no probe requests
```

Levels: `quick` 25 pages, `surface` 100 pages sampled one per URL pattern (default), `full` up to 500 pages.

Reports land in `site-audits/<host>/<date>-<level>.md`, next to squirrelscan's full JSON.

## Limits

- Offline mode reads raw HTML and does not run JavaScript, so it under-reports on sites built mostly in JavaScript.
- Links to other sites are not checked offline.
- It does not read Google Search Console, which is the only source of Google's own verdict on which pages it has indexed.
- Scores are squirrelscan's. Compare them only with earlier squirrelscan runs of the same site at the same level, not with Semrush or Ahrefs.

## Development

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -v
```

Tests use synthetic fixtures in `tests/fixtures/` and a fake `squirrel` binary, so they need no network. The report parser targets squirrelscan JSON `schemaVersion` 1.x and refuses anything else.

## Licence

MIT. squirrelscan is a separate project under its own MIT licence; this skill only calls its CLI.
