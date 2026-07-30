---
name: site-audit-scanner
description: Read-only website crawler and rendered-page auditor for SEO, content, links, images, schema, Open Graph, accessibility, mobile UX, security headers, and loading diagnostics. Use when Codex needs to scan a finished or staging website, replace a browser SEO analyzer such as Plerdy for repeatable audits, compare releases, find site-wide SEO defects, or export an evidence-based Markdown/JSON report without modifying the target.
---

# Site Audit Scanner

Audit only targets the user owns or explicitly authorizes. Keep every scan
read-only: GET public pages, never submit forms, log in, mutate data, follow
logout/delete links, or apply fixes without a separate request.

## Workflow

1. Confirm target URL or local document root. Prefer staging/local before
   production.
2. Create a new output directory outside served webroot.
3. Run deterministic crawl:

```bash
python3 <skill-dir>/scripts/site_audit.py <target> \
  --output <output-dir> \
  --max-pages 200
```

4. Read `summary.md` and `audit.json`. Treat heuristics as leads, not Google
   ranking guarantees.
5. For JS-heavy pages, visual/mobile checks, dynamic lazy-load, dialogs, or
   console errors, perform rendered-browser pass from
   `references/rendered-browser-pass.md`. Never infer rendered DOM solely from
   raw HTML.
6. When the user wants Plerdy-style AI UX analysis, read
   `references/ai-ux-pass.md`. Produce qualitative attention/scroll-risk
   evidence and test hypotheses; never fabricate heatmap percentages.
7. Classify findings:
   - `critical`: blocks access, crawl, indexing, or core conversion;
   - `high`: strong SEO/UX/accessibility failure;
   - `medium`: material quality issue;
   - `low`: improvement or manual review.
8. Deliver outcome first: release decision, critical/high findings, evidence,
   then prioritized fixes. Separate verified defects from hypotheses.

## Scan modes

- HTTP(S): same-origin crawl from links and sitemap. External links are listed,
  not fetched.
- Local directory: crawl HTML files without starting a server. Use this for
  source-level checks, then run browser pass against a local server.
- Single page: set `--max-pages 1`.

Useful options:

```bash
--sitemap <URL-or-path>   explicit sitemap
--exclude <regex>         repeatable path exclusion
--timeout 15              request timeout
--fail-on high            non-zero exit when high/critical findings exist
```

Never use `--exclude` to hide failures from a final report. State excluded
paths and why.

## Required audit surfaces

Always cover:

- status/redirects, canonical, robots, sitemap and indexability;
- unique title, description and H1 across pages;
- heading hierarchy, visible text metrics, repeated titles/descriptions;
- internal links, fragments, hash-only links and broken targets;
- image alt, dimensions, responsive attributes, lazy loading and broken files;
- Open Graph, X/Twitter metadata and JSON-LD validity;
- semantic landmarks, labels, interactive names and basic form safety;
- mobile 320 px overflow, keyboard flow, Escape/focus restore, touch targets;
- JS/lazy-rendered content, console errors and failed resources;
- security headers and mixed-content references;
- HTML weight, resource counts, fetch timings and large-page warnings;
- E-E-A-T/AEO/search-intent signals as manual heuristics only.

Detailed rule meaning and limitations:
`references/checks.md`.

Plerdy feature mapping and deliberate limits:
`references/plerdy-parity.md`.

## Evidence rules

- Record URL, rule ID, severity and exact evidence.
- Never report a missing element without showing checked page(s).
- Do not call interpolation “4K quality” or claim speed from local timing.
- Do not claim Core Web Vitals from synthetic fetch timings.
- Do not claim search ranking, uniqueness, E-E-A-T, or accessibility compliance
  from heuristics alone.
- For localhost, label network timing as local and non-production.
- Preserve secrets: strip credentials/query tokens; do not include cookies,
  authorization headers, form values, private admin paths, or source maps in
  reports.

## Release decision

Use:

- `BLOCKED`: critical defect or core workflow fails.
- `STAGING-READY`: local/source checks pass; production environment unverified.
- `PRODUCTION-READY`: production-like staging passes, owner inputs exist,
  forms/admin/backup tested, and no unresolved critical/high finding.

An all-green static crawl cannot produce `PRODUCTION-READY` without rendered
browser and server-side acceptance.
