# Real-user speed data (Chrome UX Report)

squirrelscan measures pages from your machine (lab data). Google ranks on what real Chrome visitors experienced over the last 28 days (field data), published in the Chrome UX Report (CrUX). `scripts/crux.py` fetches that for the whole site and `audit_sites.py` calls it automatically when a key is set.

## Get a key (free, about 5 minutes)

1. In the Google Cloud console, create or pick a project.
2. APIs & Services → Library → enable **Chrome UX Report API**.
3. APIs & Services → Credentials → Create credentials → **API key**. Restrict it to the Chrome UX Report API.
4. Export it where your shell or agent can see it, e.g. in `~/.bashrc` or a secrets manager:
   ```bash
   export CRUX_API_KEY=...
   ```

The API is free with a quota of 150 queries a minute per project, which a handful of sites never approaches. The script never prints or saves the key.

## Reading the numbers

The report shows the 75th percentile: three quarters of visits were at least this good. Google's thresholds:

| Measure | Good | Poor |
|---|---|---|
| Largest Contentful Paint (main content visible) | ≤ 2.5 s | > 4.0 s |
| Interaction to Next Paint (response to a tap or click) | ≤ 200 ms | > 500 ms |
| Cumulative Layout Shift (layout jumping) | ≤ 0.1 | > 0.25 |

LCP, INP and CLS are the three Core Web Vitals. FCP and TTFB are shown as supporting detail.

## "Not enough data"

CrUX only publishes a site once it has enough Chrome visitors. Small or new sites often return no data (HTTP 404). That is not an error and not a bad score; rely on squirrelscan's lab hints for those sites.

## Manual check

```bash
python3 scripts/crux.py --origin https://example.com
python3 scripts/crux.py --url https://example.com/pricing/ --form-factor PHONE
```
