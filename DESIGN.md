# Simple Soccer – Design Guide

Single source of truth for the look of every menu, table and report screen.
**If a screen needs something that is not described here, add it here first, then build it in `scripts/ui/ui_kit.gd`.**
No screen should hard-code a colour, font size or spacing: use the tokens below via `UIKit`.

Principles
1. **Readable first.** Data screens are for scanning: aligned numbers, clear rows, one highlighted thing per screen (usually the player's own team).
2. **One accent.** Yellow is the only accent. It means "yours / important / primary action". Never use it for decoration.
3. **Calm dark surfaces, layered.** Depth comes from three surface levels, not from borders or shadows.
4. **Consistency over cleverness.** Same component = same look everywhere (a table in Teams looks like a table in the Tournament).

---

## 1. Tokens

### Colour (already in `UIKit`)
| Token | Hex | Use |
|---|---|---|
| `BG` | `#12161d` | screen background |
| `PANEL` | `#1c222c` | cards, table body (surface 1) |
| `PANEL2` | `#272f3d` | table header, buttons, zebra rows (surface 2) |
| `PANEL3` | `#323c4e` | hover, selected (surface 3) |
| `ACCENT` | `#ffd54a` | primary action, user's team, key numbers |
| `TEXT` | `#e8ecf2` | primary text |
| `MUTED` | `#8d98ab` | secondary text, column headers, hints |
| `GOOD` | `#62d26f` | wins, positive, qualification |
| `BAD` | `#ef6a5b` | losses, negative, eliminated |

Extra tokens (in `UIKit`): `LINE = #2d3646` (dividers), `PANEL_ALT = #20262f` (zebra row), `HILITE = #3a3a30` (highlighted row: accent tint over `PANEL`), `SCRIM = black @ 70 %` (overlays).

Rules: text on `PANEL`/`PANEL2` is `TEXT` or `MUTED` only. Team kit colours appear only as small swatches/logos, never as text colour on a data screen.

### Type scale (Godot default font, sizes in px)
| Role | Size | Colour | Example |
|---|---|---|---|
| Display | 56–64 | `ACCENT` | game title, final score |
| H1 | 32 | `ACCENT` or `TEXT` | screen title |
| H2 | 22 | `TEXT` | section title, round name |
| Body | 18 | `TEXT` | default text, table cells |
| Caption | 14 | `MUTED` | subtitles, hints, notes |
| Column header | 13 | `MUTED`, UPPERCASE | table headers |

Numbers in tables are always Body 18; the most important column (Pts, Grade) is the same size but `ACCENT`/rating colour and bold-weight via a larger size (+2).

### Spacing (4-pt grid)
`4 · 8 · 12 · 16 · 24 · 32`. Screen margin = 32. Gap between cards = 16. Gap inside a card = 8–12. Card padding = 16.

### Shape
Corner radius: **8** for buttons/rows, **12** for cards. No borders; use surface level and 1 px `LINE` dividers instead.

---

## 2. Components (all live in `ui_kit.gd`)

### Buttons – three levels, max one primary per screen
- **Primary**: `ACCENT` fill, dark text (`BG`), height 52. The thing you want the player to do next ("Play my match", "Start Tournament", "Continue").
- **Secondary** (default): `PANEL2` fill, `TEXT`, height 44.
- **Ghost**: no fill, `MUTED` text, hover `PANEL2`. Back / Save & Menu / Quit.
Buttons have a visible focus ring (2 px `ACCENT`) for keyboard use.

### Card
`PANEL` fill, radius 12, padding 16. Optional title row: H2 left, caption right. Never nest a card inside a card; use a divider.

### DataTable (new – replaces every `GridContainer` table)
Used by: league/group table, player ratings, top-player lists, teams/squads.
- **Header row**: `PANEL2` fill, 13 px UPPERCASE `MUTED`, height 36, radius 8 on the top corners.
- **Body rows**: height **44**, alternating `PANEL` / `PANEL` + 4 % white (zebra), 1 px `LINE` between sections only (not every row).
- **Column spec**: each column declares `title`, `width` (fixed px or expand), `align`. **Text columns left-aligned, numeric columns right-aligned**, with a fixed width so numbers line up vertically across rows and tables.
- **Highlight row** (the player's team / man of the match): `HILITE` background + 4 px `ACCENT` bar on the left edge + `ACCENT` text for the name.
- **Key column** (Pts, Grade): bigger/accent colour; rating cells use `rating_color()`.
- **Zone markers** (league/groups): 4 px bar on the left edge of the row in `GOOD` for qualification places, none otherwise.
- Cell padding: 12 px horizontal. Team cells are `logo 28 px + 12 px gap + name`.
- Horizontal scrolling is never allowed. The base viewport (1280 px wide, stretch `expand`) is the minimum width, so all columns always fit; keep total fixed column widths under ~1000 px.

### Segmented tabs (replaces `TabContainer` look)
Pill row under the header: inactive = `MUTED` text, active = `PANEL3` pill with `ACCENT` text. Height 40, radius 8, gap 8. Content sits 16 px below.

### Fixture card (tournament Match Day / Results)
One row per match inside a card: `[home name ▸ right-aligned] [logo] [score box] [logo] [◂ away name]`.
- Score box: fixed 96 px wide, `PANEL2`, radius 8, H2 size; "vs" in `MUTED` when unplayed; penalties as a caption below ("pens 4–3").
- The player's fixture: `HILITE` background and `ACCENT` names.
- Results tab: the scorers/MoM line sits under the row in Caption, centred, `MUTED`.

### Stat comparison row (match report)
`value | label | value`, label centred in `MUTED`, the larger value in `ACCENT`. Optional thin bar (6 px) under each side, proportional.

### Leaderboard card (Players tab)
Card with H2 title, then rank `1..8` (MUTED), logo 24, name, value right-aligned in `ACCENT`. Rank 1 gets a slightly larger row.

### Form controls
OptionButton/CheckBox: `PANEL2` fill, height 44, radius 8, label (Caption, `MUTED`) **above** the control rather than in a separate grid column on narrow screens.

---

## 3. Screens

| Screen | Layout |
|---|---|
| **Main menu** | Centred column (420 px): Display title, caption subtitle, 1 Primary ("Continue Tournament" if a save exists, else "Quick Match") + Secondary buttons, Ghost "Quit". Footer hint in Caption. |
| **Quick match / Tournament setup** | Left: one card per group of settings (Teams · Pitch · Rules). Right: live preview card (logo, style, rating, pitch name/size). Bottom bar: Ghost "Back" left, Primary "Start" right. |
| **Tournament hub** | Header card (logo 56, title H1, subtitle caption, Ghost "Save & Menu" right) → segmented tabs → content. Match Day: round name H2, fixture card, action bar (Control selector, Primary "Play my match", Secondary "Simulate round"). |
| **Table tab** | One DataTable per league/group, columns: `# · Team · P · W · D · L · GD · Pts` (GF/GA available at wide widths). Group tables each in their own card with "Group A" H2. |
| **Results tab** | Rounds as cards, newest round first; fixture cards inside. |
| **Players tab** | 2×2 grid of leaderboard cards. |
| **Match report** | Score header (Display) → scorers (two columns) → stat comparison card → one DataTable per team (`# · Player · Pos · Grade · G · A · Shots · Passes · Rec · Saves`) with man of the match as the highlight row → Primary "Continue". |
| **Teams & squads** | Team list left (selected = `PANEL3` + accent bar), squad DataTable right. |

In-match HUD: translucent top bar only (score, clock, team names). No on-screen control hints; they appear in the pause screen.

---

## 4. Implementation rules
- All styling goes through `UIKit` (`ui_kit.gd`). New helpers: `UIKit.primary_button`, `UIKit.ghost_button`, `UIKit.card`, `UIKit.segmented_tabs`, `UIKit.DataTable` (class building a `Control` from a column spec + rows).
- Colours/sizes come from `UIKit` constants (`UIKit.FS_H1`, `UIKit.SP_16`, …); never literals in screen scripts.
- A screen is allowed one Primary button.
- Screens must work at 1280×720 up to a fullscreen MacBook (16:10); use containers and expand flags, no absolute positions.
- Keyboard: Enter = Primary action, Esc = Back/Ghost where it makes sense.

## 5. Rollout plan
1. ✅ **Foundation** – add tokens, button variants, card, segmented tabs and `DataTable` to `ui_kit.gd`; update the theme (focus ring, hover). *(no screen changes yet)*
2. ✅ **Tables** – migrate the league/group table, then player tables in the report and Teams screen to `DataTable`. Biggest readability win.
3. ✅ **Tournament** – restyle hub header + tabs, fixture cards, Results grouping, leaderboard cards, champion screen.
4. ✅ **Setup & menu** – card-grouped settings with live preview, primary/secondary/ghost buttons, main menu hierarchy.
5. ✅ **Polish** – keyboard shortcuts (Enter = primary, Esc = back), focus ring, consistent headers; narrow-width column dropping is not needed because the 1280×720 base viewport is the minimum width. Run `experiments/ui_smoke.tscn` to regenerate screenshots and check every screen against this guide.
