# Soccer Lab – Design Guide

The look of the **Lab** area of the web app (the experiment dashboard: `web/lab/*.js`, `web/style.css`). The Game area has its own
guide, [docs/design.md](design.md), and its own stylesheet (`web/game.css`); the two never share colours or components.
**If a Lab page needs something that is not described here, add it here first, then build it.** No page hard-codes a colour, a
font size or a spacing: use the tokens below (CSS variables on `:root` in `web/style.css`).

Principles
1. **Readable first.** The Lab is for scanning numbers: aligned tabular figures, one highlighted thing per card, labels on every axis.
2. **One accent.** Green (`--accent`) means "running / selected / this run". Status colours (`--good`, `--bad`, `--warn`) only for
   meaning (better, worse, evaluating), never for decoration.
3. **Calm, flat surfaces.** Depth from two surface levels and a 1 px line; no gradients, no shadows in dark mode.
4. **Fits the screen.** Pages are designed for a MacBook (1280×800 to 1440×900 viewports). Now and Live fit without scrolling;
   long lists are paginated, never endless; nothing scrolls sideways.
5. **One source per thing.** A component exists once (in `web/lab/core.js` or as a CSS class) and every page uses it.

---

## 1. Tokens (`web/style.css` `:root`; light theme under `:root[data-theme="light"]`)

### Colour
| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0d1117` | `#f4f5f7` | page background |
| `--panel` | `#151b23` | `#ffffff` | cards (surface 1) |
| `--panel-2` | `#1b222c` | `#f6f7f9` | table header, inputs, hover (surface 2) |
| `--line` | `#273140` | `#e1e5ea` | card border, dividers |
| `--grid` | `#1f2833` | `#edf0f3` | chart grid lines, empty bars |
| `--ink` / `--ink-2` / `--muted` | `#e8edf3` / `#c3ccd7` / `#8b97a6` | `#141a22` / `#3d4856` / `#6b7686` | text: primary / secondary / captions |
| `--accent` (+ `--accent-soft`) | `#3cc488` | `#1f8f5f` | running, selected, the focus run |
| `--good` `--bad` `--warn` (+ `-soft`) | green / red / amber | darker variants | better / worse / evaluating, paused |
| `--c1` … `--c10` | | | run colours (hashed from the run name, so a run keeps its colour everywhere) and chart series |

### Type (system UI font; numbers always `tabular-nums`)
| Role | Size / weight | Token |
|---|---|---|
| Page title | 20 / 650 | `--fs-title` |
| Card title | 14 / 600 | `--fs-h` |
| Body, table cells | 13 | `--fs-body` |
| Caption, axis labels, table headers | 11.5 | `--fs-cap` |
| KPI value | 20 / 650 | `--fs-kpi` |
| Eyebrow (small uppercase label) | 11 / 650, letter-spacing .06em | – |

### Spacing (4-pt grid)
`--sp-1 4 · --sp-2 8 · --sp-3 12 · --sp-4 16 · --sp-6 24`. Page gutter 24. Gap between cards 12. Card padding 12 × 14. Radius 10
(cards), 8 (controls), 99 (pills).

### Charts
Fixed heights: `--chart-s` 150, `--chart-m` 210, `--chart-l` 270 px. The width always follows the card (the chart is redrawn at the
card's real width), so a wide card never makes a tall chart.

---

## 2. Layout
- **12-column grid**: `.grid` with spans `.s3 .s4 .s5 .s6 .s7 .s8 .s9 .s12` (below 1000 px every span is full width). Cards in one row
  stretch to the same height.
- **Page head**: `.head` = title (+ one-line caption) on the left, the page's main controls on the right, on one line.
- **Full-height pages** (Live): `.fit` makes the page exactly the window below the bar; its content shares that height.

## 3. Components (classes in `web/style.css`, builders in `web/lab/core.js`)

| Component | Use | Builder / class |
|---|---|---|
| **Card** | every block of content | `.card`; title row `cardHead(title, side)` (h2 left, caption or controls right); `.card.flush` for edge-to-edge tables |
| **KPI tile** | one number with a label and a sub-line | `kpi(label, value, sub, cls)` → `.kpi` |
| **State** | a run's state in tables | `.st.running`, `.st.done`, … (dot + text) |
| **Badge** | a state in a title | `badge(state)` → `.badge` |
| **Chips** | what a run changes (rewards, args) | `chips(row)` → `.chip`, `.chip.rw` (reward), `.chip.net` |
| **Segmented control** | one choice of a few (size, entry, mode) | `seg(name, options, value)` → `.rseg`; a click calls `onSeg[name](value)` |
| **Filter bar** | filters above a table | `.fbar` (every control 32 px high) |
| **Table** | lists | plain `<table>`; header on `--panel-2`; text left, numbers right (`.r`); row link = `tr.link` |
| **Pager** | every list longer than one page | `pager(key, rows, size)` → `{rows, html}`; 25 rows by default, 5–10 inside small cards |
| **Chart** | lines over updates or time | `lineChart(series, {size, xTitle, yTitle, …})`: grid, ticks, both axis titles, one legend row (click hides a series), hover tooltip |
| **Elo** | any rating | `eloText(elo, pm, est)` (`~` and grey for an estimate, `±` the 95 % interval); label with `eloKind(entry)`: *player Elo* (a player as five copies of itself), *team Elo* (a line-up), *checkpoint Elo* (a training checkpoint, rated like a player) — never mix the three in one list |
| **Timeline** | what happened in the last 24 h | `timeline(overview)`: the runs one after another on one track in their colours, marks for checks, finishes, stops and reboots |
| **Notes** | a run's description | `notes(key, text, lines)`: clamped to 1–2 lines with a *more* toggle |
| **Empty state** | no data | `.empty`: one sentence that says why and when data comes |

### Chart rules
- Every chart has an x title and a y title (`update`, `time`, `Elo`, `goals / match`, …) and at most ~6 ticks per axis.
- Size S for small multiples (3 per row), M for the main chart of a card, L only for a full-width chart.
- Uncertainty: vertical 95 % bars (estimates) or a band; reference values as dashed horizontal lines with a label at the right.
- Colours: a run's own colour for its series; `--good` / `--bad` for scored / conceded; the palette `--c1…` in order for anything else.

### Tables
- 25 rows per page (`pager`), the header stays visible (`th` is sticky inside `.card.flush`).
- At most one emphasised column (Elo); the focus row (this run) is `tr.focus` (accent tint).
- Long text never widens a column: `.clip` (ellipsis) or wrap in a sub-line (`.muted.small`).

## 4. Pages
| Page | Layout |
|---|---|
| **Now** | Fills the window like a dashboard, no scrolling. Run strip (full width: name, stage, chips, one-line notes, KPIs, progress bar with a tick per Elo check, curriculum stages, queue) → row: estimated Elo chart (s5) · Live mini card (s4) · machine (s3) → row: ratings top 5 with Players / Teams / Checkpoints (s5) · timeline + the latest events (s7); the two rows share the height left. |
| **Live** | Full height: the match (drawn by the Game's renderer, `web/game/render.js`) and a 260 px side panel (run progress, both sides' Elo, mode, camera, opponent). |
| **Runs** | Filter bar → paginated table, the latest run first (sortable by Elo and the other columns). |
| **Run** | Header (name, state, chips, notes clamped, a fact grid on the right) → tabs: Summary · Training · Evaluation · Behaviour · Scouting · Setup (observation, actions, rewards, training). |
| **Compare** | Run chips + add / presets → Elo and goals table (the judging numbers) → Elo and goals charts → folded full-evaluation details. |
| **Ranking** | Head with the size control → filter bar (entry, league, search) → paginated table → rating history · latest matches. |
| **Events** | Filter bar → paginated feed with day separators. |

## 5. Implementation rules
- Colours, sizes and spacing only through the tokens; inline `style` only for computed widths and run colours.
- One function per card; a page function only arranges cards.
- New shared pieces go into `web/lab/core.js` and this guide.
- Check every page in both themes (the bar's ☀ / ☾ button) at 1280×800 and 1440×900.
