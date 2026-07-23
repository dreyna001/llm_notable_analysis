# Analyst Portal Theme — "Federal SOC Dark"

Theme for the AWS Alert Analysis Portal, ported July 2026 from the shared
"Federal SOC Dark" design (source of truth: the `ai-enabled-ato` portal). It
blends two directions:

- **Palette**: SOC dark console — near-black blue-gray surfaces with a
  saturated blue accent and high-contrast status colors. Matches the
  Splunk/Grafana/SIEM tooling cyber analysts already use.
- **Edges and type**: USWDS conventions — square 2px corner radius and
  Public Sans for UI text with Roboto Mono for identifiers (case IDs,
  digests, TTP codes).

Implemented in `frontend/analyst-portal/src/index.css`. The portal runs
dark-only via `<html class="dark">` in `frontend/analyst-portal/index.html`;
both `:root` and `.dark` carry identical dark values so there is never a
light fallback. No extra libraries — CSS variables plus two Google Fonts
imports.

**Visual reference (open in any browser):**
[`theme-mockups/federal-soc-dark-reference.html`](theme-mockups/federal-soc-dark-reference.html)
— workflow mockup, palette swatches, CSS variable table, and accessibility
contrast ratios.

## Palette

| Role (shadcn variable)   | Hex       | Usage                                    |
| ------------------------ | --------- | ---------------------------------------- |
| `--background`           | `#0d1117` | Page background                          |
| `--card` / `--popover`   | `#161b22` | Cards, panels, popovers                  |
| `--secondary` / `--muted`| `#1c2129` | Muted fills, selected rows, secondary buttons |
| `--border` / `--input`   | `#30363d` | Borders, input outlines                  |
| `--foreground`           | `#e6edf3` | Primary text                             |
| `--muted-foreground`     | `#8b949e` | Secondary/muted text                     |
| `--primary`              | `#1f6feb` | Primary buttons, focus ring (WCAG AA 4.6:1 with white text) |
| `--primary-foreground`   | `#ffffff` | Text on primary                          |
| `--destructive`          | `#f85149` | Errors, malicious verdicts, failed states |
| `--link`                 | `#58a6ff` | Link-styled text and blue text accents (`text-link`) |
| `--sidebar`              | `#10141a` | Sidebar background                       |

`--primary` (#1f6feb) is fill-only on dark: as standalone text it reads too
dim. Blue text (links, TTP labels) uses `--link` (#58a6ff) via the
`text-link` utility.

Status colors: `Badge` variants in
`frontend/analyst-portal/src/components/ui/badge.tsx` use Tailwind
`emerald-400` / `amber-400` text on 15%-tinted fills — the dark-mode readable
steps of those hues (`*-700` steps are tuned for light backgrounds and are
not used).

## Accessibility

- Primary buttons: white on `#1f6feb` = 4.6:1, passes WCAG AA. The brighter
  `#2f81f7` from the original SOC mockup fails at 3.7:1 with white text and
  is not used for filled buttons.
- Body text `#e6edf3` on `#0d1117` is about 15:1; muted text `#8b949e` about
  6.2:1; destructive `#f85149` about 5.6:1 — all pass AA on the page
  background.

## Shape and type

- `--radius: 0.125rem` (2px). shadcn's derived `--radius-sm`/`--radius-md`
  clamp to 0, so small controls render fully square — intentional, per the
  USWDS look.
- UI text: `Public Sans` (fallback: Source Sans Pro, system stack).
- Identifiers/code: `Roboto Mono`, applied through the Tailwind `--font-mono`
  token (covers `code`, `kbd`, `pre`, `samp`, and `.font-mono`).
- Base body size 14px, antialiased.
- Fonts load from Google Fonts in `index.css`; system fallbacks keep the
  portal usable if the CDN is unreachable.

## Deviations from the source theme

- `:root` carries the same dark values as `.dark` (the source keeps a light
  `:root`); this portal is dark-only, so a light fallback is never rendered.
- The scrollbar utility is named `.chat-scrollbar` here (`.portal-scrollbar`
  in the source); styling is identical.
- Layout, spacing, and page composition are intentionally NOT inherited from
  the source app — the theme port covers design tokens and component color
  conventions only.
