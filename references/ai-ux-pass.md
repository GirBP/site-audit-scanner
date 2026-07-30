# AI-assisted UX/CRO pass

Use after technical crawl and rendered browser pass. This is a qualitative
expert heuristic, not a real-user heatmap.

## Inputs

- Full-page desktop and mobile screenshots.
- Above-fold screenshots.
- DOM snapshot and primary conversion path.
- Business goal, target audience and primary CTA.
- Real analytics only when user provides authorized access/data.

## Review

For each viewport, identify:

1. Likely first attention target from size, contrast, placement and whitespace.
2. Primary CTA visibility, wording, contrast and competing actions.
3. Visual hierarchy: headline → proof/value → CTA → supporting detail.
4. Friction: dense copy, ambiguity, hidden controls, surprise navigation,
   excessive choice, weak trust or inaccessible interaction.
5. Scroll-drop risk per section: repetition, weak transition, no information
   scent, oversized media, delayed proof or CTA.
6. Mobile-specific thumb reach, sticky elements, viewport occupation and
   interruption.

## Output

Create a table:

| Finding | Viewport/section | Evidence | Impact | Confidence | Fix/test |
|---|---|---|---|---|---|

Then propose at most five A/B hypotheses:

- one variable per test;
- expected user mechanism;
- primary metric;
- guardrail metric;
- minimum observation condition;
- no invented uplift percentage.

## Limits

Never draw numeric click probability, scroll-depth percentage, conversion
uplift, or “AI heatmap” values without a validated model or real analytics.
Call visual attention zones `predicted qualitative attention`, not measured
behavior. Validate important decisions with GA4/Search Console, event tracking,
session recordings, interviews, and accessibility testing.
