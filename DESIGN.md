---
version: alpha
name: ProjectA_1
description: A precise forecasting workbench for Thai business owners.
colors:
  background: "#f5f7fb"
  surface: "#ffffff"
  text: "#142238"
  muted: "#697991"
  border: "#e1e8f1"
  primary: "#5b4fe7"
  action: "#594ce4"
  teal: "#079d94"
  sidebar: "#0f1d33"
typography:
  display:
    fontFamily: "Space Grotesk, IBM Plex Sans Thai, sans-serif"
  body:
    fontFamily: "IBM Plex Sans Thai, DM Sans, sans-serif"
  utility:
    fontFamily: "DM Sans, sans-serif"
rounded:
  DEFAULT: "0.625rem"
  card: "0.8125rem"
spacing:
  page-gutter: "3.625rem"
  card-gap: "1rem"
components:
  button: {}
  card: {}
  input: {}
  navigation: {}
---

# ProjectA_1 Design System

## Overview

The product should feel like a compact forecasting workbench for a Thai business owner: precise, calm, and trustworthy. The signature is a dark ink navigation rail beside a bright analytical canvas, with teal for observed sales and indigo for the forecast horizon. Avoid fabricated metrics or a marketing-style dashboard. This is a product workspace used frequently on desktop and occasionally on mobile.

Thai is the primary language, with English available through a visible switch. Numerical dates use ISO in data tables to avoid ambiguity. The runtime CSS in `app/globals.css` is canonical; this document mirrors its accepted shared values. CSS variables map directly to surface, text, border, primary, and chart roles. Dark mode remaps semantic colors under `data-theme="dark"`.

## Colors

`background`, `surface`, `text`, `muted`, and `border` establish information hierarchy. `primary` marks the future forecast line and accents; `action` is the darker solid-button fill that keeps white button text legible in both themes; `teal` marks observed sales. The sidebar has its own dark surface. Success and error banners use semantic tinted backgrounds and readable text. Dark mode remaps the same hierarchy without changing meaning. Runtime CSS variables in `app/globals.css` own exact values; this file records accepted intent and mirrors those values.

Forecast review notices use the `caution-*` semantic tokens from `app/globals.css` in both themes. They are persistent and include the measured reason in text; color alone never signals reliability.

## Typography

Display headings and large numbers use Space Grotesk with IBM Plex Sans Thai fallback. Thai body and controls use IBM Plex Sans Thai. Small utility labels use DM Sans. Keep Thai line height generous enough for marks and mixed-script labels. Never rely on browser default control type.

## Layout

Desktop navigation is a 252px rail. The main canvas has a maximum width of 1536px, a 58px gutter on wide screens, and a two-column analysis region. Below 720px navigation becomes a fixed five-item bottom bar so every destination remains visible. Data tables scroll within their own surface; forms preserve normal document scrolling.

## Elevation & Depth

Use subtle borders and a faint shadow on data surfaces. The forecast chart remains the dominant panel. The dark next-step strip is the only secondary expressive surface; do not add heavy shadows or nested cards inside every section.

## Shapes

Controls use approximately 10px radii; panels use 13px. Buttons are solid for the primary action and outlined for secondary actions. Focus rings are explicit and visible in both themes.

## Components

Buttons have hover, focus, busy, and disabled states. Navigation has selected state and semantic buttons. Inputs have visible labels and inline errors. Empty states explain the next action. The chart uses teal for actuals and dashed purple for forecast; a daily table provides an accessible numeric alternative. Success/error messages use live regions and can be dismissed.

Iconography uses one outline SVG family instead of mixed Unicode glyphs. Motion is brief and purposeful: staggered card arrival, directional navigation feedback, chart reveal, and press states. All animation is removed under `prefers-reduced-motion`. No animation should imply a value changed when data did not.

The brandmark is a transparent pixel-art black cat with gold eyes and a red bow on a pale lavender tile. It appears on the login panel, desktop navigation rail, and browser icon. Its one-time scale entrance is decorative and never conveys model status. Motion inspired by Motion Reference uses a 600ms, 24px fade-and-slide for newly mounted content, a 520ms logo pop, and a 680ms one-shot focus pulse for selected navigation and positive feedback. Charts and numeric values remain stable while data changes; reduced-motion mode suppresses these effects.

## Do's and Don'ts

The forecast workspace uses the HelloGrowthCRM reference for information hierarchy: horizon and segment controls, a dominant actual-versus-forecast chart, concise period totals, and a context rail. It retains the existing palette and Thai-first type. No confidence ribbon, sales target, deal card, or probability is shown without measured data. The rail exposes recency, eligible-series coverage, WAPE, and review status. On small screens it follows the chart.

- Do show actual imported data and measured model quality.
- Do preserve Thai-first wording and predictable control labels across screens.
- Don't display placeholder business numbers as if they were real.
- Don't hide key mobile navigation items behind horizontal scrolling.
