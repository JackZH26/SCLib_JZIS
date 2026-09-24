# Taste Skill frontend iteration

## Design read and pre-edit audit

Reading this as a research-library redesign for superconductivity researchers,
with a precise, calm visual language built on the existing SCLib identity.
Mode: Preserve. This is an iteration on the integration branch, not a new site.

Source: https://www.tasteskill.dev/guide and the linked `design-taste-frontend`
SKILL.md, also installed at `/Users/jackzhou/.codex/skills/design-taste-frontend/SKILL.md`.
The guide's sample approval prompts are examples; the user has requested that
the frontend iteration be implemented. No separate design approval is assumed
necessary for reversible changes within the existing brand and architecture.

- Brand: accent #3A7D5C, deep accent #24503A, background #f0f5f0,
  surface #e8f0e8, ink #2d3b2d. Inter via next/font. Existing SCLib by JZIS
  wordmark. Controls use 10px radii; content surfaces use 12px.
- Architecture: root search-first home; Search, Materials, Reported Tc Timeline,
  Discovery, Resources, About JZIS. Account entry remains Sign in or Dashboard.
  Research, Join, Data & methodology and API documentation remain secondary pages.
- Preserve: brand, default English, functional search, scientific caveats,
  original API/auth behavior, all legacy redirects, real cached aggregate data,
  legal/consent copy, existing field names and data interpretation.
- Improve: undifferentiated green surfaces, weak active-navigation feedback,
  understated search affordance, visually repetitive homepage, long information
  pages without a contents navigation, and contrast of search placeholders.
- Existing dials inferred: DESIGN_VARIANCE 3, MOTION_INTENSITY 2,
  VISUAL_DENSITY 4. Updated: 5 / 3 / 4. Asymmetry distinguishes the landing
  composition; motion only acknowledges interaction; research density is retained.
- SEO baseline: preserve the existing H1, titles, descriptions, canonical URLs,
  structured data, route slugs, home section IDs, and the contact anchor.
  Search rankings have not been measured; no ranking claim is made.

## Scope and contextual adaptations

The skill's landing-page patterns apply to the home, shared shell and information
pages. Materials, search results and scientific workbenches remain product UI:
do not replace tables, hide scientific qualifications, or add eight marketing
sections merely to meet a greenfield example. Keep one light theme and the
established font/accent. No added animation or icon dependency is necessary.

Use one lightweight generated conceptual artwork on the homepage, clearly
identified as illustration, not experimental evidence. Additional decorative
images would compete with the library's primary search task. Keep scientific
versions accessible as provenance rather than promotional footer decoration.

## Implemented changes

- Asymmetric search-first hero, retaining the exact original H1 and metadata.
- Cached, real library aggregates move nearer the top; failure still shows the
  existing unavailable state, never illustrative numbers.
- Materials gets a larger entry alongside Timeline and Discovery, with a separate
  evidence interpretation section. All existing scientific caveats remain.
- White, 73px shared header; explicit active state; keyboard skip link; Escape
  restores focus to the menu button. Existing account session logic is unchanged.
- Visible search label, stronger input/placeholder contrast, unchanged `q` name,
  query encoding, target and minimum length.
- Information pages gain a responsive contents navigation. Existing explicit
  anchors such as `contact` remain. Only missing H2 anchors are added.
- Search gains a semantic H1. Materials receives a clearer heading and more
  comfortable filter controls; field order, labels and scientific copy stay intact.
- Footer links stay intact. Authentic site/data versions remain available in a
  native provenance disclosure.

## Preservation audit

- Removed or renamed URLs: none.
- Changed primary navigation labels: none.
- Changed form names or ordering: none.
- Removed or renamed existing anchors: none. Added `main-content`,
  `institution-heading` and local contents anchors derived from existing H2 text.
- Changed title/description/canonical/structured metadata: none.
- Changed legal or consent copy: none.
- Existing Inter font, green accent tokens, wordmark treatment and light theme
  retained. The deep brand shade is used for small text links on pale green to
  meet contrast requirements, while the primary button retains its brand color.
- Home sections: asymmetric search/visual hero; horizontal metric band;
  featured-entry grid; evidence text/notice split; compact institutional block.
  Five purposeful sections, not eight artificially added marketing sections.

## Artwork provenance

Generated with the built-in image_gen tool, not the API/CLI fallback.
Project assets under `/Users/jackzhou/Documents/SCLib_JZIS-integration-20260924/`
(responsive WebP encoding only; no compositing):

- `frontend/public/images/layered-material-concept-640.webp`: 30,878 bytes.
- `frontend/public/images/layered-material-concept-1120.webp`: 90,212 bytes.

Original generated file:
`/Users/jackzhou/.codex/generated_images/01a0d10f-db82-79b3-ba11-bb2c86235faf/exec-e90379b9-745e-4cc9-8504-a0457bef304b.png`.
Alt text and the visible caption identify the work as AI-generated conceptual
illustration. It is not a measurement, experimental specimen or claimed research.

Prompt used:

> Use case: stylized-concept. Asset type: SCLib scientific research library website hero artwork, landscape 3:2, 1536 by 1024 if supported. Create one refined abstract material study: a close-up sculptural stack of thin fractured graphite and pale ceramic planes, subtle crystalline grain, quiet dark forest-green reflections between layers, on an off-white light sage background. Tactile, precise, restrained editorial 3D still life, oblique macro view, soft daylight from upper left, nuanced physical shadows, calm scientific publishing aesthetic. A few large overlapping mineral-like planes, no glitter and no shiny gemstone, no familiar electronic device. Fill the lower right two-thirds of the frame with the layered forms; airy pale background at upper left. Colors: off-white, pale sage #e8f0e8, charcoal green #2d3b2d, subtle accent #3A7D5C. This is purely abstract conceptual artwork, not a depiction of a real sample or measurement. No text, no numbers, no labels, no plots, no diagrams, no atoms or orbital paths, no microscope UI, no human, no logo, no watermark, no neon, no blue-purple gradients.

## Validation

- 46 source tests and 1,923 component/protocol tests passed.
- TypeScript passed; 29 production-mode Playwright checks passed. These cover
  responsive layout, search submission, keyboard focus, contents anchors, root
  and legacy URLs, auth cache headers, reduced motion and local image budgets.
  Browser traffic is isolated; search receives an explicit synthetic empty result.
  No real user account, email or production search was used for those tests.
- Browser inspection at 320, 390, 768, 1024, 1280 and 1440px: no horizontal
  overflow; hero heading at most two lines; search button ends above 486px.
- Contrast: white/button 4.92:1 at the lightest gradient stop; input placeholder
  on white 5.70:1; muted copy on sage background 5.16:1, on sage surface 4.90:1.
- Local screenshots are layout evidence, not a production performance benchmark.
  Field Core Web Vitals and production auth success have not been measured here.
- No backend, scientific protocol, account, dependency or deployment change in
  this iteration. Production remains subject to the existing integration gates.


## Section 14 pre-flight matrix

Pass is assessed for this Preserve-mode scope; contextual adaptations are explicit.

| Check | Result | Evidence / scope |
|---|---|---|
| Brief inference | Pass | Declared before editing: researcher-facing, precise and calm. |
| Dial values | Pass | 5 / 3 / 4, with reasons in the audit above. |
| Design system | Pass | Existing Next.js, Tailwind 3 and SCLib tokens retained; no claimed third-party design system. |
| Redesign mode | Pass | Preserve mode; tokens, architecture, copy and SEO recorded before editing. |
| ZERO em-dashes (`—`) anywhere on the page. | Pass | No em/en dashes in the authored home or information-page copy. Existing scientific records, source quotations and legal copy are outside this copy-edit scope. |
| Page Theme Lock | Pass | One explicit light theme; no section inversion. |
| Color Consistency Lock | Pass | Existing green accent and its deep shade throughout. |
| Shape Consistency Lock | Pass | Existing soft scale: 8px nested controls, 10px actions, 12px grouped surfaces. Existing avatar circles retained. |
| Button Contrast Check | Pass | Primary button minimum white-text contrast 4.92:1. |
| CTA Button Wrap | Pass | CTA labels remain one line; action styles specify nowrap. |
| Form Contrast Check | Pass | Visible label; 5.70:1 placeholder contrast; deep focus outline. Accessible name includes the visible label. |
| Serif discipline | Pass | Inter retained; no serif introduced. |
| Premium-consumer palette check | Pass | Not a premium consumer brief; existing scientific-library palette retained. |
| Italic descender clearance | Pass | No italic display type introduced. |
| Hero fits the viewport | Pass | At most two headline lines at 320-1440px; 19-word subtext; search within first viewport. |
| Hero top padding | Pass | Hero top padding 12px or 20px, below the 96px cap. |
| Hero stack discipline | Pass | Headline, short description and search/secondary-action group. Visible form label is retained for accessibility; image caption discloses illustration provenance. |
| EYEBROW COUNT (mechanical) | Pass | Zero section eyebrows; the unchanged wordmark is a brand element, not a section label. |
| Split-Header Ban | Pass | Section headings have vertically stacked content. |
| Zigzag Alternation Cap | Pass | No repeated alternating image/text sections. |
| No Duplicate CTA Intent | Pass | One search action and one existing Browse materials link. Repeated navigation destinations retain familiar labels; no competing signup funnel. |
| Logo wall = logo only | Pass | No logo wall or invented social proof. |
| Bento Background Diversity | Pass | Context adaptation: three functional research entry links use a featured sage surface and two white surfaces; decorative imagery inside data-entry links would not help the task. |
| "Used by / Trusted by" logo wall | Pass | No trusted-by claims or logos added. |
| Copy Self-Audit | Pass | New copy reviewed for clear English; research caveats and data labels retained. |
| Motion motivated | Pass | Brief hover/press transitions communicate interaction, not background activity. |
| Marquee max-one-per-page | Pass | No marquee. |
| Navigation on ONE line | Pass | 73px header; desktop links remain on one line; narrower widths use the existing menu. |
| Section-Layout-Repetition | Pass | Five meaningful sections: asymmetric hero, metric band, featured-entry grid, evidence split, institutional block. Greenfield eight-section minimum is not applied to this research service. |
| Bento has rhythm AND exact cell count | Pass | Three destinations occupy three grid cells; the featured item spans two rows on desktop; all stack on mobile. |
| Long lists use the right UI component | Pass | Footer groups stay short; document contents are navigable, responsive lists. |
| Real images used | Pass | Built-in imagegen artwork supplied and visibly identified. A single asset is appropriate here; no fake UI or experimental images. |
| No pills/labels overlaid on images | Pass | No labels over the artwork. |
| No photo-credit captions as decoration | Pass | Caption explains that the image is conceptual and AI-generated; no fictional photographer credit. |
| No version footers | Pass | Context adaptation: real dataset/site provenance remains in a native disclosure because this is a scientific library, not a promotional version stamp. |
| No micro-meta-sentences | Pass | No such text. |
| No decoration text strip at hero bottom | Pass | No decorative strip. |
| No floating top-right sub-text | Pass | No floating header explainer. |
| No scoring/progress bars with filled background tracks | Pass | No new scoring bars. Scientific views remain unchanged. |
| No locale / city-name / time / weather strips | Pass | No decorative location/time strips. Institutional location in existing About copy preserved. |
| No scroll cues | Pass | No scroll cue. |
| No version labels in hero | Pass | No version label in the hero. |
| No section-numbering eyebrows | Pass | No numbered eyebrows. |
| No decorative dots | Pass | No decorative dots. |
| No `border-t` + `border-b` on every row | Pass | Dividers separate major content groups, not every data row. |
| Content density | Pass | Primary copy remains concise; longer scientific limitations are preserved intentionally. |
| Quotes ≤ 3 lines | Pass | No promotional quotes. |
| Motion claimed = motion shown | Pass | Motion dial is 3; restrained interaction transitions are implemented. |
| GSAP sticky-stack / horizontal-pan | Pass | No GSAP, pinning or scroll hijack. |
| No `window.addEventListener('scroll')` | Pass | No scroll listener introduced. |
| Reduced motion | Pass | New entry/press transitions and existing header transitions suppressed under reduced motion. |
| Dark mode | Pass | Explicit light theme is retained even when OS preference is dark; no unsupported dark-mode claim. |
| Mobile collapse | Pass | Hero, entry grid and information page explicitly collapse below their breakpoints; tested at six viewport widths. |
| Viewport stability | Pass | Root uses min-height: 100dvh; image has intrinsic dimensions and a reserved aspect ratio. |
| `useEffect` animations | Pass | No animation effects introduced; keyboard listener retains cleanup. |
| Empty / loading / error | Pass | Cached statistics unavailable state retained; existing search loading/error/empty behavior unchanged. |
| Cards omitted | Pass | Containers group actual metrics, route choices and a scientific interpretation notice; prose uses open spacing. |
| Icons | Pass | No new icon package or SVG drawing. Existing menu bars and textual directional arrows retained. |
| Motion | Pass | CSS interaction transitions only; existing interactive leaf components stay client-only. |
| No AI Tells | Pass | Inter is an existing brand choice, not a default substitution. No invented metrics, logos, testimonials or generic three-equal feature cards. |
| Core Web Vitals | Pass | No new JS dependency. Responsive artwork is 31/90 KB with dimensions. Field LCP/INP/CLS are not claimed; lab layout and asset checks support plausibility only. |
| One design system | Pass | One existing styling system; no additional component system. |
