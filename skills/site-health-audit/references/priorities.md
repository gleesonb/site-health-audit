# How findings are prioritised

squirrelscan runs about 280 rules and labels each finding *error*, *warning* or *info*. That label says how sure the rule is that something is wrong, not how much it matters to the business. `scripts/priorities.json` re-sorts findings into three tiers for a small marketing, SaaS or club website. Edit that file to change a priority; the tests check it stays valid.

## How a tier is chosen

1. A rule listed under `rules` gets that tier.
2. Otherwise the rule's category (the part before `/`) gets its `categoryDefaults` tier.
3. A `messageOverrides` entry can move one *check* within a rule, matched on its message, e.g. "Title too short" drops to tier 3 while a missing title stays tier 1.
4. A failing check at squirrelscan severity *error* is raised to at least tier 2.
5. `duplicateOf` drops a finding that squirrelscan reports twice under two rules.
6. *info* findings are left out; they are notes, not problems.

## Tier 1: fix now

Anything that stops search engines finding or listing pages, breaks something visitors use, or makes the site look unsafe or unfinished:

| Theme | Rules | Why |
|---|---|---|
| Accidentally hidden pages | `crawl/indexability`, `crawl/all-noindex-pages`, `crawl/noindex-in-sitemap`, `crawl/robots-txt`, `crawl/robots-meta-conflict`, `crawl/indexability-conflicts`, `core/robots-meta`, `crawl/schema-noindex-conflict` | A page with `noindex`, or blocked in robots.txt, never appears in Google, whatever its content. |
| Wrong main version | `core/canonical`, `crawl/canonical-chain` | A canonical tag tells Google which URL is "the" page; a wrong one hands the ranking to another URL. |
| Broken journeys | `links/broken-links`, `links/invalid-links`, `images/broken-images`, `reliability/*`, `crawl/soft-404` | Visitors hit dead ends; search engines waste their visit on errors. |
| Redirect detours | `crawl/redirect-chain`, `links/redirect-chains` | Each hop slows the visitor and leaks some ranking value. |
| Sitemap | `crawl/sitemap-*` (exists, valid, 4xx, domain) | The sitemap is the list of pages you ask Google to index; dead entries erode trust in it. |
| Titles | `core/meta-title` (missing), `core/title-unique`, `content/duplicate-title` | The title is the blue link in search results. Missing or duplicated titles make pages compete with each other. |
| HTTPS | `security/https`, `security/http-to-https`, `security/mixed-content`, `security/tls-certificate`, `security/form-https`, `links/https-downgrade` | Browsers warn visitors about insecure pages and forms. |
| Looks unfinished | `content/placeholder-*`, `content/dev-leakage`, `content/unrendered-markup`, `content/mojibake` | Template text, staging links or `&amp;` on the page read as a neglected site. |
| Leaked secrets | `security/leaked-secrets` | An API key in page source is a security incident, not an SEO issue. |

## Tier 2: fix soon

Costs clicks, speed, shares or accessibility, but nothing is broken: page speed (`perf/*` default; Google's Core Web Vitals are a ranking signal), images over 1 MB and images without size or alt text, missing meta descriptions, structured data errors (`schema/json-ld-valid`, Organization, breadcrumbs), Open Graph tags for link previews on LinkedIn and social sites, thin pages, mobile layout, cookie consent and privacy pages (`legal/*`, a legal requirement in the EU and UK), and the accessibility checks that block someone from using a form or link (`a11y/form-labels`, `a11y/button-name`, `a11y/link-text`, `a11y/color-contrast`).

## Tier 3: worth a look

Everything else by default: length nags for titles and descriptions, most accessibility polish, URL style, E-E-A-T signals, security headers such as CSP and security.txt, minification, and AI-agent readiness (`ax/*`, including llms.txt). Google states that Search does not use llms.txt, and whether to let AI crawlers in is a business decision, so the skill reports it without judging it.

## Things the tiers cannot know

- Whether a page is *meant* to be hidden or gated. A 401 "broken link" to a password-protected partner page may be deliberate; say so rather than calling it broken.
- Whether a single-language site needs hreflang (it does not).
- Business priorities: a broken link on the pricing page matters more than one on a 2019 blog post. When presenting results, point out findings on key pages first.
