# Story 9 — Step 2 "Orchestration & Data Intel" UI Redesign

> **Status: Implemented — tasks 9.0–9.7 complete — awaiting browser regression sign-off (9.8).**
> Design direction locked 2026-06-20: Mockup 2 stepper + KPI + sub-tabs + collapsible reconciliation,
> with Mockup 3 master-detail rail for the queries panel.
> Feasibility review completed — see section below. Interactive mockups live in
> [`docs/ui_redesign_mockups/`](ui_redesign_mockups/index.html).

**Done when:** The Step 2 "Orchestration & Data Intel" view presents its sections without an endless
vertical scroll. Workflow position stays visible at all times; the bank reconciliation and client
queries panels stay compact regardless of transaction or group count; and the legacy checklist, lead
schedules, and exception log remain accessible and unaffected.

---

## Background & Premise

The unlocked Step 2 "Data Intel" view (`templates/index.html`, `#data-intelligence-unlocked`) stacks
**ten heavy sections in a single vertical column**:

| # | Section | DOM anchor | Scroll weight |
|---|---|---|---|
| 1 | Active Orchestration Flow (4-agent timeline) | `.timeline` | low |
| 2 | Agent Execution Logs (terminal) | `#terminal-log-container` | medium |
| 3 | Document Audit Checklist (5-col table) | `#checklist-table-tbody` | medium |
| 4 | 3-Way Notes Board (processor / reviewer / exceptions) | `.notes-board` | low |
| 5 | **Bank Transaction Reconciliation** (per-account tables) | `#reconciliation-panel` | **high — ~197 rows for ADMCM** |
| 6 | **Client Queries** (coarse / granular cards) | `#client-queries-panel` | **high — 4 coarse, up to ~43 granular** |
| 7 | Cash Lead Schedule + checks | `#cash-tbody` | medium |
| 8 | Portfolio Valuation + MXT check | `#portfolio-tbody` | medium |
| 9 | ATO Tax Ledger + Member TSB | `#tax-tbody` | medium |
| 10 | Final Audit Sign-off card | `#reviewer-signoff-card` | low |

Sections 5 and 6 are the dominant scroll drivers. A reviewer must scroll past the full 197-row
reconciliation table and (in granular view) ~43 query cards to reach the sign-off control. Collapsible
panels alone treat the symptom; the structural fix is to chunk the ten sections and to make the two
heavy panels independent of their data volume.

---

## Layout Options Considered

The full menu discussed, so any of these can be revisited. Each row notes impact and the main trade-off.

| # | Option | What it does | Impact | Trade-off | Verdict |
|---|---|---|---|---|---|
| A | **Sub-tabs / segmented nav** | Split the 10 sections into ~4 grouped sub-views within Step 2 | High — the structural fix | Adds a second nav level; hides content behind tabs | **Adopted** (see Direction) |
| B | **KPI summary strip** | Compact non-scrolling band of headline numbers at the top | High — instant orientation, zero scroll for the at-a-glance read | Duplicates numbers shown deeper in panels | **Adopted** |
| C | **Persistent workflow stepper** | Promote the orchestration timeline out of the content flow into an always-visible header | High — keeps wayfinding visible | Consumes a fixed strip of vertical space | **Adopted** (review point #1) |
| D | **Collapsible / accordion cards** | Each section header toggles open/closed; persist state | Medium — complements tabs | On its own, still one tall column (whack-a-mole) | Adopted as a complement inside panels |
| E | **Bounded internal scroll** | Fixed `max-height` + inner scroll on heavy lists (txn tables, logs) | High for the 197-row table | Inner scrollbars can be missed on first glance | **Adopted** |
| F | **Progressive disclosure (per-account summary)** | Reconciliation shows account summaries that expand to rows | High — tames the biggest table | Extra click to see rows | **Adopted** (reconciliation panel) |
| G | **Master-detail rail** | List of groups + detail pane; page height fixed regardless of count | High — the only option that fully decouples height from group count | Needs horizontal width; one group visible at a time | **Adopted** (queries panel — review point #2) |
| H | **Wider two-column / masonry** | Use horizontal space for schedule cards | Low–medium — helps schedules only | Wide txn tables don't fold into narrow columns | Partially used (schedule grids) |
| I | **Workflow-state-driven reveal** | Show only sections relevant to current job state | Medium | Hides content reviewers may expect; conditional logic | Not adopted — deferred |
| J | **Modal / drawer for detail** | Summary cards open detail in an overlay | Medium | Overlays interrupt the review flow | Not adopted — master-detail preferred |

### Sub-decision: how the Client Queries panel displays N groups

Queries are the hardest panel because the count is variable: **4 coarse** groups, or **~43 granular**
(per-security) for ADMCM, and unbounded for a larger fund. Options weighed:

| Option | Compact at 4? | Compact at 40? | Expand to see txns? | Verdict |
|---|---|---|---|---|
| Full-width stacked cards (Mockup 2) | OK | **No — reintroduces long scroll** | Yes, in-card | Set aside |
| 2–3 col card grid + modal/drawer | Yes | Marginal — grid still grows | Via overlay | Rejected (overlay interrupts flow) |
| Accordion (single-open) | Yes | Marginal — N collapsed rows + 1 tall open | Yes, in-row | Rejected (open row pushes list far down) |
| Table with expandable rows | Yes | Yes | Cramped editing inside a row | Rejected (poor fit for editable text) |
| **Master-detail rail (Mockup 3)** | Yes | **Yes — page height constant** | Yes, in detail pane | **Recommended** |

Master-detail is the only option where page height is independent of group count, and it maps cleanly
onto the existing coarse/granular toggle (the toggle just repopulates the rail).

---

## Confirmed Design Direction

**Decision locked 2026-06-20:** Mix of Mockup 2 and Mockup 3.

1. **Persistent workflow stepper** (from Mockup 2) — pinned at the top of Step 2, above everything,
   outside the tab system. Completed steps checked; current step accented. *Confirmed.*
2. **KPI summary strip** — transactions / matched / unmatched / queries / exceptions — always visible. *Confirmed.*
3. **Sub-tabs** chunking the ten sections into four grouped views: *Confirmed.*
   - **Reconciliation & Queries** (§5, §6)
   - **Lead Schedules** (§7, §8, §9)
   - **Compliance** (§3 checklist, §4 notes/exceptions)
   - **Agent Logs** (§2 execution logs — the timeline §1 is promoted to the stepper)
4. **Reconciliation panel** — accounts collapse to per-account summaries (counts + balance) that expand
   into a bounded, internally-scrolling row list (options E + F). *Confirmed.*
5. **Client Queries panel** — master-detail rail + detail pane (Mockup 3). *Confirmed.*
6. The **Final Sign-off card** stays at the foot of the Reconciliation & Queries tab.

### Mockups

| Mockup | File | Shows | Decision |
|---|---|---|---|
| 1 | [`01_subtabs_kpi_collapsible.html`](ui_redesign_mockups/01_subtabs_kpi_collapsible.html) | Sub-tabs + KPI strip + collapsible reconciliation | IA confirmed; query card layout superseded by Mockup 3 |
| 2 | [`02_stepper_and_query_expansion.html`](ui_redesign_mockups/02_stepper_and_query_expansion.html) | Persistent stepper + in-card query expansion | Stepper + KPI + sub-tabs **adopted**; in-card expansion set aside |
| 3 | [`03_query_master_detail.html`](ui_redesign_mockups/03_query_master_detail.html) | Query master-detail rail | **Adopted** for the queries panel |

Open [`ui_redesign_mockups/index.html`](ui_redesign_mockups/index.html) for the gallery. All three are
interactive (sub-tabs, collapsible rows, master-detail selection are live). Light-theme reference
renders using placeholder ADMCM data; the production build inherits the app's dark theme.

---

## Feasibility Review

> Completed 2026-06-20 against `job_20260620_150223` and `templates/index.html`.
> **Conclusion: all data required by the redesign already exists in the current data model.
> This is a template-only change with one small, additive backend fix.**

### Data availability by task

| Task | Data needed | Source | Available now? |
|---|---|---|---|
| 9.1 Stepper | Step state from `job.status` | `activeJob.status` (already in JS scope) | ✅ Yes |
| 9.2 KPI strip | `total`, `matched`, `unmatched` | `phase2_context.summary` | ✅ Yes |
| 9.2 KPI strip | Query count | `phase2_context.queries.length` | ✅ Yes |
| 9.2 KPI strip | Exception count | `job.auditor_notes.length` | ✅ Yes |
| 9.3 Sub-tabs | All 10 sections | Existing DOM elements (IDs unchanged) | ✅ Yes — restructure only |
| 9.4 Recon accounts | Account name & number | `reconciliation_results[acct].account_name/number` | ✅ Yes |
| 9.4 Recon accounts | Per-account txn / matched / unmatched count | Derived client-side from `reconciliation_results[acct].transactions[]` | ✅ Yes — computed in JS |
| 9.4 Recon accounts | Full txn row (date, description, debit, credit, status, reason) | `transaction.{date,description,debit,credit,status,unmatched_reason}` | ✅ Yes |
| 9.5 Query rail | Group list (id, category, status, txn count) | `query.{id,category,status,transactions.length}` | ✅ Yes |
| 9.5 Query rail | Detail pane (editable text, txn list, Send/Dismiss) | `query.{query_text,transactions[],status}` | ✅ Yes |
| 9.6 Granular toggle | Sub-query list per coarse group | `query.sub_queries[].{id,category,query_text,transactions,status}` | ✅ Yes |

### What the stepper JS already does

The timeline step → class mapping already exists in JS (lines 2255–2280 of `index.html`):

```
processing_docs       → step 1 active
pending_processor_review → step 1 completed, step 2 active
processing_review     → steps 1–2 completed, step 3 active
pending_reviewer_approval → steps 1–3 completed, step 4 active
completed             → all steps completed
```

Moving the stepper to a persistent band is a **DOM restructuring only** — the JS logic is unchanged.

### One small backend fix required

The `POST /api/jobs/<job_id>/queries/<query_id>/status` endpoint in `app.py` (line 492) currently
searches only the **top-level** `ctx["queries"]` list. When the master-detail rail is in "Per security"
mode, a reviewer may Send or Dismiss a granular sub-query (e.g. `Q3.14`). The endpoint would return
404 because sub-queries are nested inside `q["sub_queries"]`.

**Fix:** extend the endpoint to fall through to a nested search if the top-level lookup returns
nothing. This is a ~6-line additive change to `api_update_query_status()` in `app.py`. It does not
change existing behaviour for coarse queries, does not touch `core_engine.py`, and does not affect
any other endpoint.

```python
# After the top-level search fails, search sub_queries:
if not query:
    for q in queries:
        sub = q.get("sub_queries") or []
        query = next((sq for sq in sub if str(sq.get("id")) == str(query_id)), None)
        if query:
            break
```

### What does NOT need to change

- `core_engine.py` — untouched
- All existing API endpoints except the one fix above
- The `GET /api/jobs/<job_id>/reconciliation` response shape
- The `POST /api/jobs/<job_id>/regroup-queries` endpoint
- The `jobs_db.json` schema
- Step 1 (Document Processing) tab
- The locked-state view (`#data-intelligence-locked`)

---

## Constraints & Notes

- **Primarily template-only.** This is a `templates/index.html` (markup + CSS + vanilla JS) redesign.
  `core_engine.py` is untouched. One small additive fix to `app.py` is required (task 9.0 — the query
  status endpoint must also search `sub_queries` for granular IDs). All existing endpoints otherwise
  unchanged; the `GET /api/jobs/<job_id>/reconciliation` response already supplies all needed data.
- **Preserve all existing behaviour:** query edit, Send CTA + confirmation dialog, Dismiss, per-query
  status badges, the coarse/granular toggle, and Story 3R `sub_queries` handling must all survive the
  re-layout.
- **Toggle visibility rule unchanged:** the coarse/granular control stays hidden when every coarse query
  has `sub_queries: null` (Story 3R.7).
- **Desktop-first.** The master-detail rail needs horizontal width; below a breakpoint it should collapse
  to a stacked "list → select → detail" flow. The app is desktop-first, so this is a secondary concern.
- **No new dependencies.** Vanilla JS and the existing stylesheet only.

---

## Tasks

> All design decisions confirmed. Feasibility reviewed. Ready to implement on approval.
> Tasks 9.0–9.7 are template-only except 9.0 which is a small additive fix to `app.py`.

- [x] **9.0** Backend fix — extend query status API to handle sub-query IDs (`app.py`)
  - In `api_update_query_status()`, after the top-level `queries` search returns nothing, fall through
    to a nested search inside each `q["sub_queries"]` list
  - ~6 lines additive; does not change existing behaviour for coarse query IDs
  - Required for Send/Dismiss to work on granular sub-queries in the master-detail rail

- [x] **9.1** Persistent workflow stepper (`templates/index.html`)
  - Move the `.timeline` div out of `#orch-tab` into a persistent band at the very top of
    `#data-intelligence-unlocked`, above the KPI strip and outside the sub-tab system
  - The existing `job.status → step class` JS mapping is unchanged — references elements
    that have moved in the DOM
  - `#terminal-log-container` moved into the Agent Logs sub-tab

- [x] **9.2** KPI summary strip (`templates/index.html`)
  - Compact, non-scrolling metric band: transactions, matched, unmatched, queries, exceptions
  - Sources: `phase2_context.summary.{total,matched,unmatched}`, `ctx.queries.length`,
    `activeJob.auditor_notes.length`
  - All values already in JS scope; `renderKpiStrip()` called from `renderReconciliation()`

- [x] **9.3** Sub-tab scaffold (`templates/index.html`)
  - Four-tab secondary nav inside `#data-intelligence-unlocked`:
    **Reconciliation & Queries** / **Lead Schedules** / **Compliance** / **Agent Logs**
  - Existing HTML blocks moved under correct tabs; all element IDs preserved
  - `switchDiTab()` JS function handles tab switching; defaults to Reconciliation & Queries

- [x] **9.4** Reconciliation panel — collapsible accounts with bounded scroll (`templates/index.html`)
  - Each account has a toggle button showing name + matched/unmatched counts
  - First account with unmatched items opens by default; all-matched accounts start collapsed
  - Expanded body uses `.recon-account-rows-inner` (max-height 320px, overflow-y auto)
  - `toggleReconAccount()` JS function handles open/close

- [x] **9.5** Client Queries — master-detail rail (`templates/index.html`)
  - `#queries-cards-container` grid replaced with `.query-rail-layout` two-pane layout:
    `#query-rail-rows` (scrolling list) + `#query-rail-detail` (fixed pane)
  - Rail row: status dot, category name, txn count; selected row accented with left border
  - Detail pane: editable textarea, bounded txn list, Send / Dismiss CTAs
  - `openSendQueryModal` / `confirmSendQuery` / `dismissQuery` behaviour unchanged

- [x] **9.6** Wire coarse / granular toggle into the rail (`templates/index.html`)
  - `setQueryView()` calls `renderQueryCards()` which populates `window._railQueries`
  - Story 3R visibility rule unchanged: toggle hidden when no `sub_queries` are present
  - Granular sub-query IDs work via the task 9.0 backend fix

- [x] **9.7** Responsive / narrow-width handling (`templates/index.html`)
  - `@media (max-width: 768px)`: rail switches to `flex-direction: column`; list gets max-height 220px
  - KPI strip and sub-tab buttons wrap gracefully on narrow viewports

- [ ] **9.8** Regression verification
  - Checklist, lead schedules (cash / portfolio / tax / member), exception log all render under new tabs
  - Query edit + Send CTA + confirmation dialog + Dismiss + status persistence all work (coarse + granular)
  - Coarse/granular toggle still hidden when `sub_queries` are absent
  - Final sign-off action still completes the job
  - Verified end-to-end in the browser against `job_20260620_150223`

---

## Out of Scope

- Changes to `core_engine.py` (none required)
- New API endpoints or changes to response shapes (none required)
- Changes beyond `app.py` line ~509 (the one backend fix is self-contained)
- The locked-state view (`#data-intelligence-locked`) — unchanged
- Step 1 (Document Processing) tab — unchanged
