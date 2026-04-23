# battleship-tui

Terminal-native Battleship — the classic naval grid game, keyboard-driven,
with a heatmap-targeting AI and a REST API for bot play.

## Features

- Two 10×10 grids per player (own fleet + targeting).
- Classic 5-ship fleet (Carrier 5, Battleship 4, Cruiser 3, Submarine 3, Destroyer 2).
- Placement phase: arrow keys + rotate + random-fleet shortcut (`R`).
- Three AI difficulties: random / heatmap / optimal (hunt-and-kill).
- Hotseat (2-human pass-and-play) + vs AI modes.
- Classic turn mode + optional salvo variant.
- Hit / miss / sunk visual feedback, sunk-ship outline on tracking board.
- Mouse clicks, keyboard, and a REST agent API.
- Synth sound effects (opt-in).

## Quick start

```bash
make all          # sets up venv + installs dependencies
make run          # vs AI, heatmap difficulty, classic mode
```

Or directly:

```bash
python battleship.py                          # vs AI (heatmap)
python battleship.py --mode hotseat           # 2 humans
python battleship.py --ai optimal --salvo     # hard AI, salvo mode
python battleship.py --sound                  # synth SFX on
python battleship.py --agent                  # expose REST API on :8765
python battleship.py --headless               # server only, no TUI
```

## Controls

### Placement phase

| Key             | Action                             |
|-----------------|------------------------------------|
| Arrow keys      | Move placement cursor              |
| `r`             | Rotate ship horizontal / vertical  |
| Space / Enter   | Place current ship                 |
| Shift+R         | Auto-place full random fleet       |
| `u`             | Undo last placement                |
| Tab or `b`      | Finish placement → battle          |

### Battle phase

| Key             | Action                             |
|-----------------|------------------------------------|
| Arrow keys      | Aim on targeting board             |
| Space / Enter   | Fire!                              |
| Mouse click     | Click to place / fire              |

### Anywhere

| Key        | Action                          |
|------------|---------------------------------|
| `?`        | Help                            |
| `l`        | Legend                          |
| `n`        | New game                        |
| `q`        | Quit                            |

## Testing

```bash
make test           # all QA + API scenarios
make test-only PAT=placement   # subset by name pattern
make perf           # render + AI + end-to-end benchmarks
make test-sound     # "I can't hear anything" diagnostic
```

## Design

Pure-Python engine (no SWIG binding). Battleship's grid-shot mechanic is
generic/folk — not copyrightable — so this is a clean-room implementation
with no vendored assets or trademarked terminology. See `DECISIONS.md`
for the full rationale.

## License

MIT.
