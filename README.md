# Site Audit Scanner

Read-only agent skill and Python crawler for repeatable SEO, content, link,
image, structured-data, accessibility, mobile UX, security-header, and loading
audits.

Designed as an open alternative to browser SEO analyzers. It combines:

- deterministic HTTP or local-file crawling;
- Markdown, JSON, and standalone HTML reports;
- rendered browser/mobile acceptance instructions;
- qualitative AI-assisted UX/CRO review;
- explicit safety and evidence rules.

It never submits forms or modifies the audited website.

## Install

### OpenAI Codex

```bash
git clone https://github.com/GirBP/site-audit-scanner.git \
  ~/.codex/skills/site-audit-scanner
```

Then invoke:

```text
Use $site-audit-scanner to audit https://example.com and produce an evidence-based report.
```

### Claude Code

```bash
git clone https://github.com/GirBP/site-audit-scanner.git \
  ~/.claude/skills/site-audit-scanner
```

Ask the agent to use `site-audit-scanner` for the target.

### Other agents

Load `SKILL.md` as the agent procedure. The deterministic scanner works
independently:

```bash
python3 scripts/site_audit.py https://example.com \
  --output ./audit-output \
  --max-pages 200
```

Requirements: Python 3.10+; no third-party Python packages.

## Outputs

- `audit.json` — full machine-readable evidence;
- `summary.md` — concise review;
- `report.html` — standalone human-readable report.

## Scope

Checks include:

- HTTP status, redirects, canonical, robots, sitemap, hreflang;
- titles, descriptions, H1–H6, duplicate metadata, text metrics;
- internal links, broken targets, anchor and rel state;
- image alt, dimensions, responsive/lazy attributes, file status and size;
- Open Graph, X/Twitter and JSON-LD;
- forms, labels, semantic landmarks and basic accessibility;
- mixed content and baseline security headers;
- TTFB approximation, HTML weight and resource counts;
- desktop/mobile rendered checks and qualitative UX/CRO hypotheses.

See `references/plerdy-parity.md` for implemented and deliberately excluded
features.

## Safety

- Audit only sites you own or are authorized to inspect.
- Same-origin public-page crawl only.
- External links are listed, not fetched.
- Admin, account, logout, delete, checkout, tokenized paths are excluded.
- No form submissions, login attempts, uploads, exploit probes, or fixes.
- Reports remove query strings and never store cookies or authorization data.

## Validation

```bash
python3 -m py_compile scripts/site_audit.py scripts/test_site_audit.py
python3 scripts/test_site_audit.py
```

The static score is diagnostic, not a Google ranking score. Fetch timing is not
Core Web Vitals. Qualitative attention predictions are not real heatmaps or
user analytics.

## License

MIT. Not affiliated with Plerdy.
