# Rendered browser pass

Use browser control after deterministic crawl when JavaScript, layout, or
interaction affects the result.

## Minimum matrix

- Desktop: 1440×900.
- Mobile: 320×568.
- Pages: home, main catalog/listing, detail or lightbox, contact/form, privacy.
- Additional breakpoints only when layout changes materially.

## Per-page checks

1. Navigate to known URL and wait for load.
2. Capture DOM snapshot before interaction.
3. Record:
   - document title, H1 count, canonical and robots;
   - horizontal overflow;
   - loaded images with `naturalWidth === 0`;
   - current hero/image source and intrinsic dimensions;
   - console warning/error and failed resources;
   - visible dialogs and accessible names;
   - touch target sizes for primary controls.
4. Test core interaction with unique role/name locators:
   - navigation/menu;
   - filter/search;
   - lightbox;
   - primary conversion CTA;
   - empty-form validation;
   - Escape close and focus restoration.
5. Take focused screenshots only when visual evidence helps.

## Dynamic SEO checks

Compare raw crawl with rendered DOM:

- title, description, canonical and robots;
- H1–H6;
- internal links;
- image alt and loaded source;
- JSON-LD;
- body text meaningful without delayed interaction.

Flag mismatch when essential content exists only after user action or raw HTML
and rendered DOM disagree.

## Safety

Do not submit real forms, send messages, log in, upload, delete, purchase, or
trigger external communication. For form testing, stop at client validation
unless user separately authorizes a controlled test endpoint.

Finalize temporary browser tabs after audit. Do not close user-owned tabs.
