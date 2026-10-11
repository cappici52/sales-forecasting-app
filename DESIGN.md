---
version: alpha
name: ProjectA_1
description: A calm, data-focused forecasting workspace for Thai business owners.
colors:
  background: "#f5f7fa"
  surface: "#ffffff"
  text: "#162338"
  muted: "#708096"
  border: "#e3e9ef"
  primary: "#5d50da"
  teal: "#168c81"
  sidebar: "#142238"
typography:
  display:
    fontFamily: "Space Grotesk, IBM Plex Sans Thai, sans-serif"
  body:
    fontFamily: "IBM Plex Sans Thai, DM Sans, sans-serif"
  utility:
    fontFamily: "DM Sans, sans-serif"
rounded:
  DEFAULT: "0.6875rem"
  card: "1rem"
spacing:
  page-gutter: "3.5rem"
  card-gap: "1.0625rem"
components:
  button: {}
  card: {}
  input: {}
  navigation: {}
---

# ProjectA_1 Design System

## Overview

The product should feel like a compact forecasting workbench for a Thai business owner: precise, calm, and trustworthy. The signature is the dark navigation rail paired with a light data canvas and one purple line for future values. Avoid fabricated metrics or a marketing-style dashboard. This is a product workspace used frequently on desktop and occasionally on mobile.

Thai is the primary language, with English available through a visible switch. Numerical dates use ISO in data tables to avoid ambiguity. The runtime CSS in `app/globals.css` is canonical; this document mirrors its accepted shared values. CSS variables map directly to surface, text, border, primary, and chart roles. Dark mode remaps semantic colors under `data-theme="dark"`.

## Colors

`background`, `surface`, `text`, `muted`, and `border` establish information hierarchy. `primary` marks actions and future forecast data; `teal` marks observed sales. The sidebar has its own dark surface. Success and error banners use semantic tinted backgrounds and readable text. Dark mode retains these meanings.

## Typography

Display headings and large numbers use Space Grotesk with IBM Plex Sans Thai fallback. Thai body and controls use IBM Plex Sans Thai. Small utility labels use DM Sans. Keep Thai line height generous enough for marks and mixed-script labels. Never rely on browser default control type.

## Layout

Desktop navigation is a 248px rail. The main canvas has a maximum width of 1440px, 56px gutter on wide screens, and a two-column analysis region. Below 720px navigation becomes a fixed five-item bottom bar so every destination remains visible. Data tables scroll within their own surface; forms preserve normal document scrolling.

## Elevation & Depth

Use subtle borders and a faint shadow on data surfaces. The forecast chart remains the dominant panel. Do not add heavy shadows or nested cards inside every section.

## Shapes

Controls use approximately 11px radii; panels use 16px. Buttons are solid for the primary action and outlined for secondary actions. Focus rings are explicit and visible in both themes.

## Components

Buttons have hover, focus, busy, and disabled states. Navigation has selected state and semantic buttons. Inputs have visible labels and inline errors. Empty states explain the next action. The chart uses teal for actuals and dashed purple for forecast; a daily table provides an accessible numeric alternative. Success/error messages use live regions and can be dismissed.

## Do's and Don'ts

- Do show actual imported data and measured model quality.
- Do preserve Thai-first wording and predictable control labels across screens.
- Don't display placeholder business numbers as if they were real.
- Don't hide key mobile navigation items behind horizontal scrolling.
