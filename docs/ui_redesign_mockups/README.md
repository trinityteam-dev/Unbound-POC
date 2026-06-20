# Step 2 UI Redesign — Mockups

Interactive reference mockups for **Story 9 — Step 2 "Orchestration & Data Intel" UI Redesign**
(see [`../STORY9_STEP2_UI_REDESIGN.md`](../STORY9_STEP2_UI_REDESIGN.md)).

## How to view

Open [`index.html`](index.html) in any browser (double-click the file, or `open index.html` on macOS).
It links the three mockups below. Each is interactive — click sub-tabs, expand account rows, and select
groups in the master-detail rail.

> Icons load from a CDN (Tabler webfont), so an internet connection is needed for them to appear. The
> mockups are light-theme reference renders with placeholder ADMCM data; the production build inherits
> the app's dark theme and live data.

## Contents

| File | Mockup | Status |
|---|---|---|
| `index.html` | Gallery / launcher | — |
| `01_subtabs_kpi_collapsible.html` | Sub-tabs + KPI strip + collapsible reconciliation | Approved IA |
| `02_stepper_and_query_expansion.html` | Persistent stepper + in-card query expansion | Stepper approved; card layout set aside (doesn't scale past ~10 groups) |
| `03_query_master_detail.html` | Query master-detail rail | **Recommended** for the queries panel |

## Why three

The mockups are a progression, not alternatives to pick one from:

1. **Mockup 1** established the information architecture (KPI strip + sub-tabs).
2. **Mockup 2** added two review refinements: the orchestration flow promoted to a persistent stepper
   (kept), and query cards that expand in place (set aside — full-width cards reintroduce the long
   scroll at 10+ groups).
3. **Mockup 3** solved the query-scaling problem with a master-detail rail whose page height is constant
   regardless of group count.

The recommended composition draws the stepper + KPI + sub-tabs + collapsible reconciliation from 1 & 2,
and the query rail from 3. See the story doc's "Recommended Direction" for the full mapping.
