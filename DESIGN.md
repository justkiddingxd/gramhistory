---
name: "Gram Prices"
description: "A blue and graphite observation log for historical price queries."
colors:
  bg: "#121a20"
  surface: "#19262f"
  raised: "#21333f"
  ink: "#edf7fc"
  muted: "#b0c3cf"
  line: "#2b3943"
  accent: "#91d5fc"
  accent-ink: "#142d3b"
  code: "#10191f"
  success: "#9cdeb3"
  error: "#ffb5ad"
  selection: "#325c75"
  light-bg: "#f5f9fc"
  light-surface: "#fff"
  light-raised: "#e6f0f6"
  light-ink: "#172c39"
  light-muted: "#506978"
  light-line: "#d0dce4"
  light-accent: "#235c80"
  light-accent-ink: "#fff"
  light-code: "#eaf2f7"
  light-success: "#21613c"
  light-error: "#a1302a"
  light-selection: "#cae8fa"
typography:
  display:
    fontFamily: "SF Pro Display, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "52px"
    fontWeight: 500
    lineHeight: 1.06
    letterSpacing: "-0.035em"
  display-mobile:
    fontFamily: "SF Pro Display, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "48px"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "SF Pro Display, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "34px"
    fontWeight: 500
    lineHeight: 1.13
    letterSpacing: "-0.035em"
  body:
    fontFamily: "SF Pro Display, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "SF Pro Display, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  code:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.8
rounded:
  inline: "4px"
  control: "8px"
  input: "8px"
  table: "10px"
  note: "10px"
  surface: "12px"
  logo: "28px"
spacing:
  "8": "8px"
  "12": "12px"
  "16": "16px"
  "18": "18px"
  "20": "20px"
  "24": "24px"
  "28": "28px"
  "32": "32px"
  "40": "40px"
  "48": "48px"
  "64": "64px"
  "72": "72px"
  "80": "80px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "13px 20px"
    height: "48px"
  button-ghost:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    size: "40px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.input}"
    padding: "10px 12px"
  navigation-active:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.accent}"
    padding: "8px 12px"
  method:
    textColor: "{colors.success}"
    padding: "7px 0"
  ai-section:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.surface}"
    padding: "44px"
---

# Design System: Gram Prices

## Overview

**Creative North Star: "Observation log"**

The interface pairs a requested date with the saved observation in a shared query sheet. Sky blue from the supplied logo carries actions and the AI entry point; graphite surfaces carry readable prose and data. Home supports immediate lookup, while the separate reference supports careful reading.

**Key Characteristics:**
- Original supplied logo, copied unchanged.
- Dark by default; explicit saved light choice persists.
- Clear Cyrillic hierarchy with monospace reserved for code.
- Real request status, currency and time provenance.

## Colors

The CSS custom properties are normative. Dark uses graphite `--bg`, blue-grey surfaces, pale ink and sky-blue `--accent`. Light mode uses cool paper, dark blue ink and a deeper blue accent. Success and errors use dedicated colors; they never depend on color alone. The AI surface reverses accent/foreground roles. There are no authored gradients; the supplied logo retains its original background.

## Typography

SF Pro Display is served as WOFF2 for UI and Russian prose, with verified Cyrillic coverage and real 400/500/600/700 faces. Regular and Medium are preloaded. The original license accompanies the font assets; source and checksums are recorded in .impeccable/sf-pro-provenance.json. System fonts remain loading/error fallbacks. IBM Plex Mono is self-hosted for code and protocol data. Above1100px, the final homepage override uses52px/1.06 for the two-line heading; the supplied logo is148px. Between901–1100px the heading is62px, and at650px or below it is48px/1.1. Docs use52px desktop,44px at901–1100px,48px at651–900px and36px mobile. Typical section headings are26–36px, prose15–19px, compact code11–12px. Inputs remain16px on mobile. Do not use the superseded72px base hero declaration as the effective desktop size: the final cascade overrides it.

## Layout

Outer content max-width1280px with48px desktop gutters,32px below1100px and20px below650px. Desktop header is89px; mobile header is117px with navigation on a second row. Home has no side rail. The hero's compact desktop treatment exposes the editable date, complete run button and start of JSON at1280×720. Request/result share a two-column sheet, stacking below650px. Above1100px, the request form places method/date in the first row and advanced/run in the second; expanded parameters occupy a full-width third row.

Docs use236px sticky navigation and64px gap; these become210px/36px below1100px. At900px the rail becomes a disclosure drawer. Section spacing is38–80px according to density. Tables and code scroll within their containers; the page itself does not scroll horizontally. Source attribution uses a chronological row. The AI file group has no surrounding frame or divider; spacing defines the grouping.

## Elevation & Depth

Surfaces use color and1px boundaries, without decorative shadows. The transient copy toast alone uses `0 8px 26px #0003`. Sticky navigation preserves reading context. Smooth anchor navigation is disabled for reduced motion; there are no entrance animations.

## Shapes

The query sheet and AI section use12px radii; fields and buttons use8px; tables, code examples and notes use10px. Boundaries are quiet neutral 1px lines. Fields use separate control-line/control-hover tokens to remain identifiable without bright outlines. The logo has28px desktop hero corners,10px header corners and9px mobile header corners. Status dots are circular. Focus is2px accent with4px offset; selection, caret and scrollbar colors derive from theme variables.

## Components

Primary buttons use accent with inverse ink; hover brightness is1.07 and disabled requests have opacity0.6. Ghost icon controls are40px with8px radii and raised hover fill. Fields are labeled, dark inset surfaces; mobile font size is16px. Tab selection uses a2px underline, ARIA selection and keyboard navigation. Response status and measured network time accompany actual JSON. Requests are abortable with a15-second timeout and race protection; empty and partial days remain distinct from errors.

The initial response is explicitly an abbreviated archival example. Copy actions expose success or failure through a live toast. Documentation search filters navigation, preserves no-results feedback and supports keyboard shortcuts. Theme state uses localStorage `gram-docs-theme`; dark is the fallback. Homepage links can preselect a method through `?endpoint=`. AI actions open `/skill.md` or copy an integration instruction; neither invents a conversation or external transmission.

## Do's and Don'ts

- Use the supplied gram-history.png for the brand.
- Keep actual response status and archived examples distinguishable.
- Preserve native form labels, visible focus and responsive reading order.
- Keep price strings, source labels and date semantics unchanged.
- Do not copy Calcmula branding or imagery.
- Do not invent current prices or service status.
- Do not nest a rounded file card inside the AI surface.
- Do not replace the logo with an invented vector imitation.

### User refinement, 2026-09-28

Load the actual SF Pro Display files on Windows as well as Apple devices; a local-only declaration does not meet the requirement. Preserve moderate rounded corners:8px controls,12px query/AI surfaces and10px tables/notes. Keep boundaries muted and avoid additional nested frames. The hero fact strip and footer slogan remain removed.
