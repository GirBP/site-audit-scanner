# Audit checks and limits

## Technical SEO

- HTTP status and redirect destination.
- One canonical absolute URL; compare with current normalized URL.
- Robots meta and `X-Robots-Tag`.
- `robots.txt` and sitemap discovery.
- One non-empty title, description, H1.
- Cross-page duplicate title, description and H1.
- `lang`, viewport, hreflang validity.
- Legacy/parameter URL and canonical conflicts.

Length thresholds are warnings, not universal ranking rules:

- title: 15–65 characters;
- description: 50–170 characters.

## Content and semantics

- Heading order and skipped levels.
- Word count, average sentence length, average word length.
- Top non-stopword terms.
- Main/nav/header/footer/address/section/article usage.
- Question headings, FAQ schema, contact/about/authorship signals.

Keyword density, readability, E-E-A-T and AEO are diagnostic heuristics. Do not
turn them into ranking promises or automatic copy edits.

## Links

- Same-origin status and missing local targets.
- Empty href, `href="#"`, JavaScript URL.
- Duplicate internal link/anchor pairs.
- External links listed with rel state; not fetched by default.
- `_blank` without `noopener`/`noreferrer`.

Fragments need rendered DOM validation when target IDs are created by JS.

## Images

- Missing/empty alt.
- Missing width/height.
- Missing `srcset`/`sizes` for large content images.
- Lazy/eager/fetchpriority consistency.
- Broken local or HTTP resource.
- Suspiciously large HTML-referenced source.

File dimensions and compression require local file access or browser evidence.
Do not infer visual quality from filename alone.

## Social and structured data

- `og:title`, `og:description`, `og:url`, `og:type`, `og:image`.
- `twitter:card`, title, description and image.
- Parse every JSON-LD block.
- Require valid JSON; list `@type` values.

Schema validity is not rich-result eligibility. Use Google Rich Results Test or
Schema.org validator separately when needed.

## Accessibility and UX

Static checks:

- image alt;
- form labels/names;
- button/link accessible text;
- landmarks and document language;
- duplicate IDs;
- inline style and comment residues.

Rendered checks:

- keyboard reachability;
- focus visibility/order/trap/restore;
- Escape behavior;
- 44×44 CSS px touch targets;
- 320 px overflow;
- reduced motion and safe area;
- dialog accessible names.

These checks are not a WCAG conformance certification.

## Performance

Crawler measures:

- TTFB approximation: request start to response headers;
- total fetch time;
- response/HTML bytes;
- declared image/script/style counts.

Localhost timing cannot represent real users. Core Web Vitals require browser
lab tooling and preferably field data from Search Console/CrUX.

## Security and privacy

Report presence of CSP, HSTS on HTTPS, X-Content-Type-Options,
Referrer-Policy, Permissions-Policy and framing policy. Flag mixed content.

Header presence does not prove secure implementation. Do not probe exploits,
authentication, admin endpoints, rate limits, or destructive paths without a
separate security-testing authorization.
