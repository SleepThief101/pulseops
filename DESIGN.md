# PulseOps — Design System & Visual Identity

> **Status:** Design Discovery Complete — Awaiting Implementation Approval  
> **Direction Chosen:** B — Meridian  
> **Date:** 2026-11-25  
> **Prepared by:** Antigravity Design Agent (impeccable v4.11.0)

---

## Table of Contents

1. [Existing Design Critique](#1-existing-design-critique)
2. [Three Design Directions](#2-three-design-directions)
3. [Recommended Direction](#3-recommended-direction)
4. [Complete Colour Palette](#4-complete-colour-palette)
5. [Typography Scale](#5-typography-scale)
6. [Spacing, Sizing & Layout](#6-spacing-sizing--layout)
7. [Component Specifications](#7-component-specifications)
8. [Page-by-Page Redesign Concepts](#8-page-by-page-redesign-concepts)
9. [Responsive Design Principles](#9-responsive-design-principles)
10. [Web Design Guidelines Audit](#10-web-design-guidelines-audit)
11. [React Architecture Notes](#11-react-architecture-notes)
12. [Implementation Approval Checklist](#12-implementation-approval-checklist)

---

## 1. Existing Design Critique

### Overall Assessment

| Category | Score | Verdict |
|---|---|---|
| Visual hierarchy | 5/10 | Page and section titles too small; KPI values undersized |
| Colour semantics | 5/10 | Emerald accent overloaded across unrelated contexts |
| Typography | 5/10 | Several sizes below minimum; all-caps table headers hurt legibility |
| Data clarity | 6/10 | Charts lack tooltips; no trend indicators on KPI cards |
| Accessibility | 4/10 | Multiple WCAG failures; interactive divs, no skip navigation |
| Component quality | 6/10 | Monolithic page files; no reusable primitives |
| Spacing & rhythm | 6/10 | Inconsistent; no clear 4px grid discipline |
| Information density | 6/10 | Acceptable but not optimised for operational scanning |

---

### Critical Problems

**1. Type sizes are too small throughout**

- Page titles: `20px` — should be `28px`
- Section / panel headings: `14.7px` — should be `20px`
- KPI values: `27px` — should be `36px`
- Chart axis labels: `11px` — below the WCAG minimum of `12px`
- Table `<th>`: `uppercase + 11.5px` — illegible at operational scanning speed

**2. Accent colour overloaded**

Emerald `#10b981` currently appears as:
- Primary action buttons
- Active nav item highlight
- Positive status badges
- Logo colour

This destroys semantic meaning. The user cannot distinguish "this is a positive metric" from "this is a primary action button" from "this is the active page."

**3. Accessibility failures**

- KPI card cells use `<div role="button">` instead of `<button type="button">` — keyboard navigation broken
- Shimmer/pulse animations not gated by `prefers-reduced-motion`
- No skip-navigation link
- No `<main>` or `<nav>` landmark elements
- Form labels insufficiently contrasted against their inputs
- Chart tooltip hit targets too small for touch

**4. KPI cards show no trend data**

None of the four KPI metrics show Δ from prior period, percentage change, or directional arrows. The user cannot determine whether a number is good or bad without navigating to a secondary view.

**5. Canvas colour is harsh**

Pure `#09090b` (near-black with cold blue undertone) creates high contrast fatigue for extended operational use. A warmer dark canvas reduces eye strain and feels more premium.

**6. Charts are side-by-side at 50/50**

Two charts displayed at equal width in a 50/50 grid forces users to split their attention. Neither chart has sufficient horizontal space to show temporal patterns clearly. Stacking charts full-width produces far better data legibility.

**7. Monolithic component files**

- `DashboardPage.tsx`: 567 lines
- `IntegrationsPage.tsx`: 595 lines
- `CopilotPage.tsx`: 320 lines

No reusable primitives exist for `KpiCard`, `ChartPanel`, `EmptyState`, `StatusBadge`. Every page re-implements common patterns differently.

---

## 2. Three Design Directions

### Direction A — Carbon Ledger

> _"Finance-grade authority. The dashboard of a CFO."_

**Aesthetic:** Cold monochrome. Very dense. High information throughput. Reminiscent of Bloomberg Terminal, Linear, Pitch.

- Canvas: `#0A0A0A` (pure near-black, no warmth)
- Panels: `#111111`
- Accent: Single — Electric Blue `#2563EB`
- Typography: IBM Plex Mono for all numeric values; Inter for prose
- Tables: compact, 36px row height, hairline dividers only
- Charts: filled area charts with hard-edged fills; no soft gradients
- Badges: outlined, monochrome, text-only

**Strengths:** Exceptional data density; serious, credible aesthetic; visually distinctive.  
**Weaknesses:** Cold and demanding; risks looking like a dev tool rather than a product; no warmth for extended sessions; difficult to implement well without a component library.

---

### Direction B — Meridian ✓ Recommended

> _"Warm clarity. The control tower of a founder who cares about craft."_

**Aesthetic:** Warm dark canvas. Two-accent semantic system. Generous whitespace. Confident typography.

- Canvas: `#0D0D0F` (warm undertone)
- Panels: `#141416`
- Accent A (action): Sky `#0EA5E9` — primary buttons, active nav, links
- Accent B (success): Emerald `#10B981` — positive metrics, success states only
- Typography: Inter across all levels; JetBrains Mono for numeric/code values
- KPI cards: standalone (not connected strip), with trend badges (↑/↓ Δ)
- Charts: stacked full-width, soft gradient fills, clear tooltips
- Badges: filled, colour-coded by semantic category

**Strengths:** Warm and comfortable for long sessions; clear semantic accent separation; achievable without new dependencies; premium without being cold.  
**Weaknesses:** Slightly less distinctive than Carbon Ledger; requires discipline to maintain warmth consistently.

---

### Direction C — Fieldstone

> _"Warm neutrals. The calm of a well-considered enterprise dashboard."_

**Aesthetic:** Medium-dark warm grey. Amber/gold accent. Subdued. Reminiscent of Notion, Craft, Linear's light mode.

- Canvas: `#1A1814` (warm brown-grey)
- Panels: `#211E19`
- Accent: Amber `#F59E0B` — primary action, highlights
- Typography: Inter; slightly larger body size (16px)
- Tables: visible row stripes; relaxed 48px row height
- Charts: bar-dominant; muted palette
- Badges: pill-shaped, filled

**Strengths:** Highly readable; least fatiguing for extended use; warm and human.  
**Weaknesses:** Less appropriate for a "control tower" operational product; amber accent reads as "warning" in most SaaS contexts; risks feeling too enterprise-conservative.

---

## 3. Recommended Direction

**Direction B — Meridian** is recommended.

| Criterion | A — Carbon Ledger | B — Meridian | C — Fieldstone |
|---|---|---|---|
| Operational clarity | ★★★★★ | ★★★★★ | ★★★★☆ |
| Extended comfort | ★★☆☆☆ | ★★★★☆ | ★★★★★ |
| Visual memorability | ★★★★★ | ★★★★☆ | ★★★☆☆ |
| Semantic colour system | ★★★☆☆ | ★★★★★ | ★★★★☆ |
| Implementation feasibility | ★★★☆☆ | ★★★★★ | ★★★★☆ |
| Product-fit (B2B SaaS ops) | ★★★★☆ | ★★★★★ | ★★★☆☆ |
| Accessibility | ★★★★☆ | ★★★★★ | ★★★★★ |

**Why Meridian:**

1. **Semantic accent separation** is the highest-priority fix. Sky for actions, Emerald for positive states — this is immediately achievable and immediately improves comprehension.
2. **Warm canvas** reduces eye strain without sacrificing the dark, operational aesthetic.
3. **No new dependencies** are needed — the existing CSS custom property system is sufficient.
4. **KPI trend badges** are the single highest-value data enhancement and fit naturally with Meridian's card-first layout.
5. **Charts stacked full-width** is a layout change that dramatically improves data legibility at zero visual cost.

---

## 4. Complete Colour Palette

### Background Tokens

```css
--bg-canvas:           #0D0D0F;   /* Page background — warm near-black */
--bg-sidebar:          #0A0A0C;   /* Sidebar — slightly darker than canvas */
--bg-surface:          #141416;   /* Primary panels, cards */
--bg-surface-subtle:   #111113;   /* Nested table rows, secondary panels */
--bg-surface-elevated: #1A1A1E;   /* Modals, dropdowns, tooltips */
--bg-surface-hover:    rgba(255,255,255,0.045); /* Row/card hover */
--bg-input:            #0F0F12;   /* Form inputs */
```

### Border Tokens

```css
--border-subtle:  rgba(255,255,255,0.07);  /* Section dividers, table grid lines */
--border-default: rgba(255,255,255,0.12);  /* Card borders, panel outlines */
--border-strong:  rgba(255,255,255,0.22);  /* Focused inputs, active states */
```

### Text Tokens

```css
--text-primary:   #F2F2F3;  /* Headings, KPI values, body */
--text-secondary: #A1A1AA;  /* Secondary labels, descriptions */
--text-muted:     #71717A;  /* Timestamps, captions, placeholders */
--text-disabled:  #52525B;  /* Disabled form fields */
```

### Accent Tokens — Action (Sky Blue)

```css
--accent-action:        #0EA5E9;               /* Primary buttons, active nav, links */
--accent-action-hover:  #0284C7;               /* Button hover */
--accent-action-text:   #38BDF8;               /* Inline text links */
--accent-action-soft:   rgba(14,165,233,0.12); /* Soft backgrounds (selected rows) */
--accent-action-border: rgba(14,165,233,0.30); /* Focused input ring */
```

### Accent Tokens — Success (Emerald — retained, restricted)

```css
--accent:        #10B981;               /* Positive metrics, success badges ONLY */
--accent-soft:   rgba(16,185,129,0.12); /* Success badge background */
--accent-border: rgba(16,185,129,0.25); /* Success badge border */
```

### Semantic State Tokens

```css
--danger:      #F43F5E;  /* Error states, destructive actions, negative Δ */
--danger-soft: rgba(244,63,94,0.12);
--warn:        #F59E0B;  /* Warnings, stale data */
--warn-soft:   rgba(245,158,11,0.12);
--ai:          #A78BFA;  /* AI-generated content, Copilot, MCP indicators */
--ai-soft:     rgba(167,139,250,0.12);
--info:        #38BDF8;  /* Informational states, neutral indicators */
--info-soft:   rgba(56,189,248,0.12);
```

### Chart Series Palette

```
Series 1: #0EA5E9  (Sky — primary metric)
Series 2: #10B981  (Emerald — positive reference)
Series 3: #F43F5E  (Rose — alerts/negative)
Series 4: #F59E0B  (Amber — warnings)
Series 5: #A78BFA  (Violet — AI/secondary)
Series 6: #71717A  (Zinc — neutral baseline)
```

### Border Radius Scale

```css
--radius-xs: 4px;
--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 10px;
--radius-xl: 14px;
```

---

## 5. Typography Scale

All text uses **Inter** (UI). Numeric/code values use **JetBrains Mono**.

| Level | Size | Weight | Line Height | Letter Spacing | Usage |
|---|---|---|---|---|---|
| Display | 32px | 650 | 1.2 | -0.03em | Hero marketing (AuthPage aside only) |
| Page Title | 28px | 600 | 1.25 | -0.02em | `<h1>` per page |
| Section Heading | 20px | 600 | 1.3 | -0.01em | Panel/card headings, `<h2>` |
| Subsection | 16px | 600 | 1.4 | 0 | Minor headings, `<h3>` |
| Body | 15px | 400 | 1.6 | 0 | General prose, descriptions |
| Body Small | 14px | 400 | 1.5 | 0 | Secondary info, table cells |
| Label | 13px | 500 | 1.4 | 0.01em | Form labels, column headers |
| Caption | 12px | 400 | 1.4 | 0.02em | Timestamps, metadata (minimum) |
| KPI Value | 36px | 650 | 1.0 | -0.03em | Primary KPI numbers (JetBrains Mono) |
| KPI Large | 42px | 650 | 1.0 | -0.04em | Hero metric (optional, single metric) |

> **Rule:** No text below `12px`. Table column headers must NOT use `text-transform: uppercase` at sizes below `13px`. If uppercase is used, minimum size is `13px` with `letter-spacing: 0.08em`.

---

## 6. Spacing, Sizing & Layout

### 4px Base Grid

All spacing must be a multiple of 4px.

```
4px   — xs  (icon padding, inline tight gaps)
8px   — sm  (badge padding, tight component gaps)
12px  — md  (card internal padding small)
16px  — lg  (default component padding, row gaps)
20px  — xl  (card padding standard)
24px  — 2xl (section gaps, panel padding)
32px  — 3xl (page section gaps)
40px  — 4xl (page-level vertical spacing)
48px  — 5xl (hero sections)
```

### Layout Dimensions

| Element | Current | Target |
|---|---|---|
| Sidebar width | 244px | 220px |
| Topbar height | auto | 56px fixed |
| Content max-width | none | 1440px |
| Content padding horizontal | 24px | 32px |
| Content padding vertical | 24px | 32px |
| Card/panel gap | 16px | 24px |
| KPI card gap | 12px | 16px |
| Table row height | auto | 44px |
| Input height | auto | 40px |
| Button height | auto | 36px (default), 40px (primary) |
| Sidebar nav item height | auto | 36px |

### Content Area Rules

- Use CSS Grid for page-level layout (not nested flex)
- KPI rail: `grid-template-columns: repeat(4, 1fr)` on ≥900px
- Charts: single-column full-width stack (not 50/50 side-by-side)
- Integrations page: 2×2 grid retained (appropriate for that page)

---

## 7. Component Specifications

### KPI Card

```
Container:
  background: var(--bg-surface)
  border: 1px solid var(--border-default)
  border-radius: var(--radius-lg)
  padding: 20px 24px
  min-height: 120px
  standalone (NOT connected strip — remove shared borders)

Label row:
  font-size: 13px
  font-weight: 500
  color: var(--text-secondary)
  letter-spacing: 0.01em
  margin-bottom: 8px
  display: flex; align-items: center; gap: 6px
  (optional icon: 14px, color: var(--text-muted))

Value:
  font-family: JetBrains Mono
  font-size: 36px
  font-weight: 650
  color: var(--text-primary)
  line-height: 1.0

Trend badge (NEW):
  display: inline-flex; align-items: center; gap: 3px
  font-size: 12px; font-weight: 500
  padding: 2px 7px
  border-radius: var(--radius-sm)
  margin-top: 10px

  Positive:  bg: var(--accent-soft);    color: var(--accent);    "↑ 4.2%"
  Negative:  bg: var(--danger-soft);    color: var(--danger);    "↓ 1.8%"
  Neutral:   bg: var(--bg-surface-elevated); color: var(--text-muted); "— 0.0%"

Interactive state:
  Replace <div role="button"> with <button type="button">
  hover: background: var(--bg-surface-elevated)
  focus-visible: outline: 2px solid var(--accent-action); outline-offset: 2px
```

### Chart Panel

```
Container:
  background: var(--bg-surface)
  border: 1px solid var(--border-default)
  border-radius: var(--radius-lg)
  padding: 24px

Header:
  display: flex; justify-content: space-between; align-items: center
  margin-bottom: 24px

  Title: 20px / 600 / var(--text-primary)
  Subtitle: 13px / 400 / var(--text-muted)

Chart area:
  min-height: 240px
  Recharts ResponsiveContainer width="100%" height={240}

Axis labels:
  fontSize: 12  (minimum — was 11, fails WCAG)
  fill: var(--text-muted)  (#71717A — passes AA for graphical objects)

Grid lines:
  stroke: var(--border-subtle)
  strokeDasharray: "4 4"

Area fill gradient:
  startColor: accent hex at 0.25 opacity
  endColor:   accent hex at 0.0 opacity

Tooltip:
  background: var(--bg-surface-elevated)
  border: 1px solid var(--border-default)
  border-radius: var(--radius-md)
  padding: 10px 14px
  font-size: 13px

Layout change:
  Remove grid-charts 50/50 — stack charts vertically, full content width
```

### Data Table

```
Table wrapper:
  background: var(--bg-surface)
  border: 1px solid var(--border-default)
  border-radius: var(--radius-lg)
  overflow: hidden

<th>:
  font-size: 13px       (was 11.5px — fails)
  font-weight: 500
  color: var(--text-secondary)
  letter-spacing: 0.01em
  text-transform: none  (remove uppercase — was uppercase at 11.5px, illegible)
  padding: 0 16px
  height: 40px
  border-bottom: 1px solid var(--border-subtle)
  background: var(--bg-surface-subtle)

<td>:
  font-size: 14px
  color: var(--text-primary)
  padding: 0 16px
  height: 44px          (was auto — now fixed for consistent density)
  border-bottom: 1px solid var(--border-subtle)

<tr>:
  transition: background 150ms ease
  hover: background: var(--bg-surface-hover)

Striping: none (hover-only, no row stripes — cleaner for dense tables)
```

### Primary Button

```
height: 36px
padding: 0 16px
font-size: 14px; font-weight: 500
background: var(--accent-action)        (#0EA5E9)
color: #FFFFFF
border: none
border-radius: var(--radius-md)
cursor: pointer; transition: background 150ms ease

hover:  background: var(--accent-action-hover)  (#0284C7)
focus:  outline: 2px solid var(--accent-action); outline-offset: 2px
active: transform: scale(0.985)

Destructive variant:
  background: var(--danger)
  hover: background: #E11D48

Ghost variant:
  background: transparent
  color: var(--text-secondary)
  border: 1px solid var(--border-default)
  hover: background: var(--bg-surface-hover); color: var(--text-primary)
```

### Status / Semantic Badge

```
display: inline-flex; align-items: center; gap: 5px
height: 22px
padding: 0 8px
border-radius: var(--radius-sm)
font-size: 12px; font-weight: 500

Variants:
  success:  bg: var(--accent-soft);  color: var(--accent)
  error:    bg: var(--danger-soft);  color: var(--danger)
  warn:     bg: var(--warn-soft);    color: var(--warn)
  info:     bg: var(--info-soft);    color: var(--info)
  ai:       bg: var(--ai-soft);      color: var(--ai)
  neutral:  bg: var(--bg-surface-elevated); color: var(--text-secondary)

Optional dot indicator:
  width: 6px; height: 6px; border-radius: 50%; background: currentColor
```

### Sidebar Navigation

```
Width: 220px (was 244px — 24px recovered for content)
Background: var(--bg-sidebar)
Border-right: 1px solid var(--border-subtle)

Logo area:
  height: 56px (matches topbar)
  padding: 0 16px
  display: flex; align-items: center

Nav section label:
  font-size: 11px; font-weight: 600
  color: var(--text-disabled)
  letter-spacing: 0.08em
  text-transform: uppercase
  padding: 0 16px; margin: 16px 0 4px

Nav item:
  display: flex; align-items: center; gap: 10px
  height: 36px
  padding: 0 12px
  border-radius: var(--radius-md)
  margin: 0 8px
  font-size: 14px; font-weight: 400
  color: var(--text-secondary)
  cursor: pointer; transition: all 150ms ease

  hover:
    background: var(--bg-surface-hover)
    color: var(--text-primary)

  active:
    background: var(--accent-action-soft)   (rgba(14,165,233,0.12))
    color: var(--accent-action-text)         (#38BDF8)
    font-weight: 500
    icon-color: var(--accent-action)

  Icon: 16px, flex-shrink: 0
```

### Form Input

```
height: 40px
padding: 0 12px
background: var(--bg-input)
border: 1px solid var(--border-default)
border-radius: var(--radius-md)
font-size: 14px; color: var(--text-primary)
transition: border-color 150ms ease

placeholder: color: var(--text-disabled)

focus:
  outline: none
  border-color: var(--accent-action)
  box-shadow: 0 0 0 3px var(--accent-action-soft)

error:
  border-color: var(--danger)
  box-shadow: 0 0 0 3px var(--danger-soft)

Form label:
  font-size: 13px; font-weight: 500
  color: var(--text-secondary)   (not var(--text-muted) — was too low contrast)
  margin-bottom: 6px
  display: block
```

### Copilot — Chat Thread

```
Message bubble:
  background: var(--bg-surface)
  border: 1px solid var(--border-subtle)
  border-radius: var(--radius-lg)
  padding: 14px 16px
  font-size: 15px; line-height: 1.6

AI indicator:
  Small badge: "AI" — bg: var(--ai-soft); color: var(--ai)
  Left border on AI messages: 3px solid var(--ai)
  (matches the left-border pattern used for proposal cards)

Proposal card:
  border-left: 3px solid <category-colour>
  Categories:
    Revenue   → var(--accent)       Emerald
    Risk      → var(--danger)       Rose
    Ops       → var(--accent-action) Sky
    AI        → var(--ai)           Violet
  background: var(--bg-surface)
  border-radius: 0 var(--radius-md) var(--radius-md) 0

Input row:
  background: var(--bg-surface)
  border-top: 1px solid var(--border-subtle)
  padding: 12px 16px
```

### Empty State

```
display: flex; flex-direction: column; align-items: center; justify-content: center
min-height: 200px; padding: 48px 24px
text-align: center

Icon: 32px, color: var(--text-disabled)
Title: 16px / 600 / var(--text-primary); margin-top: 12px
Description: 14px / 400 / var(--text-muted); margin-top: 6px; max-width: 320px
CTA button (optional): margin-top: 20px
```

---

## 8. Page-by-Page Redesign Concepts

### Dashboard

**Changes:**
- KPI rail: 4 standalone cards at `grid-template-columns: repeat(4, 1fr)`, each with trend badge
- Remove the connected-strip border design — isolate each card
- Charts: remove `grid-charts` 50/50 — render vertically, each at full content width
- MRR chart first, GitHub Activity chart second
- Telemetry strip: retain, but increase row height to 44px and label font to 13px
- Topbar: add "as of [timestamp]" in `var(--text-muted)` for data freshness

**Before/After KPI layout:**
```
Before: [MRR][Churn][Issues][Cycle] — connected horizontal strip with shared borders
After:  [MRR ↑4.2%] [Churn ↓1.1%] [Issues ↑2] [Cycle ↓0.3d] — 4 isolated cards with trend badges
```

---

### Copilot

**Changes:**
- Increase chat message font from implied 14px to 15px with 1.6 line-height
- Add left-border colour coding on AI messages (3px var(--ai) border)
- Proposal cards: left-border colour by category (see Component Specs above)
- Input box: increase height to 44px; placeholder text to 15px
- "Thinking…" indicator: add `prefers-reduced-motion` gate on spinner animation
- Section heading "AI Copilot": 20px / 600

---

### Integrations

**Changes:**
- Retain 2×2 grid layout (appropriate for 4 distinct panels)
- Increase panel heading sizes to 20px / 600
- Status badges in integrations table: use semantic badge component
- Sync runs table: 44px row height; timestamp to caption (12px var(--text-muted))
- CSV import dropzone: add dashed border `var(--border-default)`; hover: `var(--border-strong)`

---

### Events

**Changes:**
- Table: 44px row height; `<th>` to 13px / 500 (remove uppercase at small size)
- Source and type filters: use ghost button group with active state using `var(--accent-action-soft)`
- Search input: full spec from Form Input above
- Expand-to-inspect panel: `border-left: 3px solid var(--border-strong)` as visual anchor
- Pagination: ghost buttons; active page: `var(--accent-action-soft)` background

---

### Team

**Changes:**
- Role matrix: render as proper `<table>` with semantic `<thead>/<tbody>` (not div grid)
- Member table: 44px row height; avatar placeholder: 32px circle, `var(--bg-surface-elevated)`
- Role badge: use semantic badge component
  - Owner: ai variant (violet — signifies elevated privilege)
  - Member: info variant (sky)
  - Viewer: neutral variant
- "Add member" form: standard Form Input spec; Submit = primary button

---

### Auth

**Changes:**
- Remove grid-pattern background from marketing aside — replace with:
  - Solid `var(--bg-canvas)` 
  - Subtle branded element: the PulseOps logo centred + one-line tagline
  - Optional: a soft gradient glow `radial-gradient(circle at 30% 60%, rgba(14,165,233,0.08), transparent 60%)`
- Auth card:
  - `border-radius: var(--radius-xl)` (14px)
  - `border: 1px solid var(--border-default)`
  - Segmented tab (Login/Register): active tab uses `var(--accent-action)`
- Error messages: danger badge variant (not plain red text)
- Submit button: full-width, 40px height, primary variant

---

## 9. Responsive Design Principles

### Breakpoints

| Breakpoint | Width | Behaviour |
|---|---|---|
| Desktop | ≥1200px | Full sidebar, 4-col KPI, side-by-side panels |
| Tablet landscape | ≥900px | Full sidebar, 4-col KPI, single-col panels |
| Tablet portrait | ≥660px | Icon-only sidebar (40px), 2-col KPI |
| Mobile landscape | ≥560px | Hidden sidebar (hamburger), 2-col KPI |
| Mobile portrait | <560px | Hidden sidebar, 1-col KPI stack |

### Sidebar Collapse

At <900px: sidebar collapses to icon-only (40px wide). Nav items show icon + tooltip on hover. Logo collapses to icon only.

At <660px: sidebar hidden entirely. Topbar gains a hamburger button that opens a slide-over drawer.

### Touch Targets

All interactive elements (buttons, nav items, table rows, badges) must have a minimum touch target of 44×44px per WCAG 2.5.5. Use padding to achieve this without changing visual size.

### Reduced Motion

All animations must be gated:

```css
@media (prefers-reduced-motion: reduce) {
  .shimmer, .pulse, .spin, [class*="animate-"] {
    animation: none;
    transition: none;
  }
}
```

---

## 10. Web Design Guidelines Audit

Findings against the Web Design Guidelines reference (Vercel Labs snapshot):

| # | Finding | Severity | Location | Fix |
|---|---|---|---|---|
| 1 | `<div role="button">` on KPI cards | Critical | DashboardPage.tsx | Replace with `<button type="button">` |
| 2 | Table `<th>` uppercase at 11.5px | High | Multiple pages | Remove uppercase OR increase to 13px |
| 3 | Chart axis labels at 11px | High | DashboardPage.tsx | Increase to 12px minimum |
| 4 | Form labels at `var(--text-muted)` | Medium | AuthPage, TeamPage | Change to `var(--text-secondary)` |
| 5 | Shimmer animation ignores `prefers-reduced-motion` | Medium | styles.css | Add `@media (prefers-reduced-motion: reduce)` gate |
| 6 | No `<main>` or `<nav>` landmarks | Medium | Layout.tsx | Wrap content area in `<main>`, sidebar in `<nav>` |
| 7 | No skip navigation link | Medium | Layout.tsx | Add `<a href="#main-content" class="skip-nav">Skip to content</a>` |
| 8 | Emerald accent overloaded semantically | Medium | styles.css | Restrict `--accent` to success states; introduce `--accent-action` for Sky |

---

## 11. React Architecture Notes

### Recommended Component Extractions

The following components should be extracted from monolithic page files during implementation. Each follows the composition patterns from `vercel-composition-patterns` (domain prop over boolean prop, explicit variant, no prop drilling).

**1. `<KpiCard>` (from DashboardPage)**
```tsx
interface KpiCardProps {
  label: string
  value: string | number
  unit?: string
  trend?: { value: number; period: string }  // positive = up, negative = down
  onClick?: () => void
}
```

**2. `<ChartPanel>` (from DashboardPage)**
```tsx
interface ChartPanelProps {
  title: string
  subtitle?: string
  children: React.ReactNode  // accepts any Recharts component
  actions?: React.ReactNode  // right-aligned header controls
}
```

**3. `<ChartTooltip>` (from DashboardPage)**
```tsx
// Recharts custom tooltip component
// Applies consistent bg-surface-elevated / border-default / 13px styling
```

**4. `<EmptyState>` (global)**
```tsx
interface EmptyStateProps {
  icon?: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
}
```

**5. `<ProposalCard>` (from CopilotPage)**
```tsx
interface ProposalCardProps {
  category: 'revenue' | 'risk' | 'ops' | 'ai'
  title: string
  description: string
  actions?: React.ReactNode
}
// Left border colour derived from category, not from a boolean prop
```

**6. `<StatusBadge>` (global)**
```tsx
interface StatusBadgeProps {
  variant: 'success' | 'error' | 'warn' | 'info' | 'ai' | 'neutral'
  label: string
  dot?: boolean
}
```

### Composition Rules

- **No boolean prop proliferation.** Use `variant: "primary" | "ghost" | "danger"` on buttons, not `isPrimary`, `isDanger`, `isGhost`.
- **Explicit children over render props.** `<ChartPanel><AreaChart /></ChartPanel>` not `<ChartPanel renderChart={() => <AreaChart />}`.
- **Domain state lives at the page level.** Primitive components (`KpiCard`, `StatusBadge`) receive only the data they display — no data fetching inside primitives.
- **React 18 constraint.** `forwardRef` is still required for DOM element refs (React 19's implicit ref forwarding is not available). Do not use the `use()` context hook.

---

## 12. Implementation Approval Checklist

Before implementation begins, confirm approval of the following decisions:

- [ ] **Direction confirmed:** Meridian (Direction B) is the chosen design direction
- [ ] **Accent change approved:** Sky `#0EA5E9` added as `--accent-action`; Emerald `#10B981` restricted to success states only
- [ ] **Canvas change approved:** Background shifts from `#09090b` to `#0D0D0F`
- [ ] **Chart layout change approved:** Charts stacked vertically (full-width), not 50/50 side-by-side
- [ ] **KPI trend badges approved:** All 4 KPI cards gain Δ trend badge (requires trend data from API or computed from existing data)
- [ ] **Typography scale change approved:** Page titles → 28px; section headings → 20px; KPI values → 36px
- [ ] **Sidebar width change approved:** 244px → 220px
- [ ] **Component extractions approved:** `KpiCard`, `ChartPanel`, `EmptyState`, `StatusBadge`, `ProposalCard`, `ChartTooltip` extracted from page files

---

*This document was prepared during the design discovery phase. No React components, CSS files, backend code, or project configuration were modified. All existing functionality is preserved.*
