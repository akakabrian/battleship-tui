# Battleship TUI — Design Decisions

## Engine: pure-Python, no SWIG binding

Battleship's game mechanic (grid-shot + place-ships) is generic/folk and not
copyrightable — the grid-shoot pattern is decades older than any specific
branded box. Hasbro's trademarks are on specific box-art, plastic peg visuals,
and the "Battleship" wordmark; the mechanic itself is free. Clean-room
implementation — no vendored ship-art, no trademarked phrases in the UI.

Pattern 4 from the skill: clean-room Python reimplementation. Same justification
as minesweeper/sudoku/chess — the logic is textbook, the state machine is
under 300 LOC, and Textual's async model runs the engine naturally in the
asyncio loop.

### Fleet

Classic five-ship fleet (17 total cells). Names are generic naval terms,
not brand-specific:

- Aircraft Carrier (5)
- Battleship (4)
- Cruiser (3)
- Submarine (3)
- Destroyer (2)

### Board

- Two 10x10 grids per player: **own board** (shows fleet + opponent's shots)
  and **tracking board** (records own shots at opponent — hit/miss only,
  no knowledge of opponent's ship layout).
- Coordinates `(x, y)` where `x` is column (0..9), `y` is row (0..9). This
  matches the simcity-tui convention.
- Columns labelled A..J, rows 1..10 — the classic display style.

### Placement

- Per-ship placement phase: arrow keys move the cursor, `r` toggles rotation
  (horizontal/vertical), space/enter places the current ship, `R` (shift+r)
  does a full random placement.
- Validate: in-bounds, no overlap with previously placed ships.
- Undo with `u` to re-place the last ship if the player changes their mind.

### Turn + shot mechanic

- Shots take `(x, y)` on the tracking board. Engine returns outcome:
  MISS / HIT / SUNK (ship's last cell) / WIN (all ships sunk) / INVALID
  (already-shot cell or off-board).
- Sunk ships are revealed on the tracking board with a ship outline so
  the shooter can see the shape of what they hit.

### Salvo mode (optional toggle)

- Variant: each turn you fire as many shots as you have ships remaining.
  Shots are queued and resolved together at end-of-turn so the player
  can't "adapt" mid-volley (matches the Milton Bradley 1967 Salvo rules).
- Default off; toggle on the new-game screen.

### AI

Three difficulties:

- **Random** — uniform over un-fired tracking cells. Never hits twice.
- **Heatmap** — parity + probability heatmap targeting. After a hit,
  switches to hunt-mode: fires at 4-neighbours of the hit, extends along
  the discovered ship axis. Never re-fires.
- **Optimal** — heatmap + keeps a full remaining-fleet constraint model,
  picks the cell that eliminates the most candidate ship placements.
  Overkill for 10x10 but shows up well.

Default AI: **Heatmap**. Cheap, fast, reads as "smart" to a human.

### Win

First player to sink all 17 opponent cells wins. Ties impossible (turns
are sequential, not simultaneous — even in Salvo, volleys resolve with
the attacker checked first).

### Hotseat + vs AI

Hotseat = 2-human pass-and-play. Between turns, a hide-board modal ("pass
the keyboard to Player 2, then press Enter") prevents peeking.
vs AI = human plays Player 1, AI plays Player 2.

## Project layout (mirrors simcity-tui / minesweeper-tui)

- `battleship.py` — argparse entry point → `run()`
- `battleship_tui/engine.py` — pure-Python engine (Game, Ship, Board, AI)
- `battleship_tui/tiles.py` — glyph + style tables (pre-parsed Styles)
- `battleship_tui/app.py` — Textual App, DualBoardView, side panels
- `battleship_tui/screens.py` — modal screens (Help, NewGame, PassBoard,
  Result, Legend)
- `battleship_tui/sounds.py` — opt-in synth SFX (tones only — debounced)
- `battleship_tui/agent_api.py` — aiohttp REST API for agents
- `battleship_tui/tui.tcss` — Textual stylesheet
- `tests/qa.py` — Pilot-driven scenarios (headless)
- `tests/api_qa.py` — agent API scenarios
- `tests/perf.py` — hot-path benchmarks
- `tests/sound_test.py` — "I can't hear anything" diagnostic

## Polish phases

- **A — UI beauty:** per-ship glyphs, shot feedback (red X hit, blue dot
  miss, highlighted sunk outline), cursor highlight on active board, salvo
  counter, clean column/row labels.
- **B — Submenus:** Help, NewGame (mode + AI + salvo toggle), PassBoard
  transition for hotseat, Result modal on win.
- **C — Agent REST API:** `aiohttp`; POST `/new_game`, `/place`,
  `/random_fleet`, `/fire`, GET `/state`. Headless mode.
- **D — Sound:** synth tones for place, fire, hit, miss, sunk, win.
- **E — Polish:** salvo mode, restart at new game, animation for sinking
  ship.
- **F — Animation:** shot-splash pulse on newly-fired cells, sinking
  ship cascade reveal.

## Game features shipped v0.1

- Placement phase: arrow keys, rotate, place, random fleet.
- Classic turn mode + optional salvo toggle.
- 3 AI difficulties (random / heatmap / optimal).
- Hit/miss/sunk feedback on tracking board.
- Win/lose detection and result modal.
- Hotseat (pass-board modal) + vs AI.
- Mouse support: click to move cursor + fire (or place).
- Agent API with JSON state snapshots.

## Not shipped (explicit non-goals for v0.1)

- Networked 2-player (LAN). The agent API can be used for cross-process
  play but a full lobby is out of scope.
- Custom fleets / board sizes. The 10x10 + classic 5-ship fleet is
  canonical; a `--custom` flag would be trivial to add later.
- LLM advisor. Battleship has essentially no strategic depth beyond
  "fire at parity-4 cells then hunt hits" — a built-in heatmap AI is
  a better fit than an LLM coach.
