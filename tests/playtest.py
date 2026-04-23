"""End-to-end pty + Pilot playtest for battleship-tui.

Boots the real `battleship.py` entry point under a pseudo-terminal via
pexpect, then drives a full match through Textual's Pilot: boot → random
fleet → start battle → fire shots → AI replies → sink a ship → quit.
SVG snapshots are written per step alongside.

Run:  .venv/bin/python -m tests.playtest
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pexpect

from battleship_tui.app import BattleshipApp
from battleship_tui.engine import (
    BOARD_H,
    BOARD_W,
    EMPTY,
    Phase,
    ShotResult,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


# --- pty boot-and-quit sanity check ---------------------------------

def pty_boot_smoke() -> bool:
    """Boot under a real pty, wait for the title, then send 'q' and
    confirm clean exit. If this fails the TUI is broken at startup."""
    repo = Path(__file__).resolve().parent.parent
    cmd = f"{repo}/.venv/bin/python {repo}/battleship.py --seed 42"
    child = pexpect.spawn(cmd, timeout=10, dimensions=(45, 140),
                          encoding="utf-8")
    try:
        child.expect("Battleship", timeout=8)
        # Give the app a beat to finish mounting, then quit.
        child.send("q")
        child.expect(pexpect.EOF, timeout=6)
        return True
    except pexpect.exceptions.ExceptionPexpect as e:
        print(f"[playtest] pty boot failed: {e}", file=sys.stderr)
        try:
            child.close(force=True)
        except Exception:
            pass
        return False


# --- driven playtest via Textual Pilot ------------------------------

async def _driven(out_prefix: str) -> int:
    """Full match walkthrough: place fleet, fire, AI replies, sink a ship, quit."""
    app = BattleshipApp(mode="vs_ai", ai="heatmap", seed=42)
    errors = 0

    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        _snap(app, f"{out_prefix}_01_boot")
        if app.game.phase is not Phase.PLACEMENT:
            print("[playtest] expected PLACEMENT at boot", file=sys.stderr)
            errors += 1

        # --- R (Shift+R) to auto-place the human fleet ---
        app.action_random_fleet()
        await pilot.pause()
        _snap(app, f"{out_prefix}_02_random_fleet")
        if not app.game.boards[0].all_placed:
            print("[playtest] random fleet did not place all 5 ships",
                  file=sys.stderr)
            errors += 1

        # --- Tab to start battle ---
        await pilot.press("tab")
        await pilot.pause()
        _snap(app, f"{out_prefix}_03_battle_start")
        if app.game.phase is not Phase.BATTLE:
            print("[playtest] did not transition to BATTLE", file=sys.stderr)
            errors += 1
        if app.boards_view.cursor_board != 1:
            print("[playtest] cursor did not move to tracking board",
                  file=sys.stderr)
            errors += 1

        # --- Fire a shot at a known-empty cell (guaranteed miss) ---
        mx, my = _first_empty_cell(app, 1)
        app.boards_view.cursor_x = mx
        app.boards_view.cursor_y = my
        await pilot.pause()
        shots_before = len(app.game.shot_log)
        await pilot.press("space")
        await pilot.pause()
        _snap(app, f"{out_prefix}_04_fire_miss")
        if len(app.game.shot_log) <= shots_before:
            print("[playtest] fire keystroke did not register a shot",
                  file=sys.stderr)
            errors += 1

        # After a miss in classic mode, the AI turn should have run
        # synchronously. Confirm AI got at least one shot in.
        ai_shots = sum(1 for s in app.game.shot_log if s["player"] == 1)
        if ai_shots < 1:
            print("[playtest] AI did not take a turn after player miss",
                  file=sys.stderr)
            errors += 1
        _snap(app, f"{out_prefix}_05_after_ai_turn")

        # --- Sink a ship: find an existing enemy ship and fire at every
        # cell until it sinks. AI turns will run in between; we force
        # turn=0 before each shot to stay on the human side. ---
        g = app.game
        target_ship = min(g.boards[1].ships, key=lambda s: s.length)
        target_cells = target_ship.cells()
        last_r: ShotResult | None = None
        b0 = g.boards[0]
        for (tx, ty) in target_cells:
            # If we already fired here (unlikely with fresh tracking), skip.
            if b0.tracking_cells[b0.idx(tx, ty)] != 0:
                continue
            g.turn = 0
            last_r = g.fire(0, tx, ty)
        app.boards_view.refresh()
        await pilot.pause()
        app.boards_view.refresh()
        await pilot.pause()
        _snap(app, f"{out_prefix}_06_sunk_ship")
        if last_r not in (ShotResult.SUNK, ShotResult.WIN):
            print(f"[playtest] expected SUNK/WIN after final hit, got {last_r}",
                  file=sys.stderr)
            errors += 1
        if not all((tx, ty) in b0.tracking_sunk_cells for (tx, ty) in target_cells):
            print("[playtest] sunk-cell outline not fully revealed on tracking",
                  file=sys.stderr)
            errors += 1

        # --- Quit gracefully ---
        await pilot.press("q")
        await pilot.pause()

    return errors


# --- helpers --------------------------------------------------------

def _first_empty_cell(app: BattleshipApp, player: int) -> tuple[int, int]:
    b = app.game.boards[player]
    for y in range(BOARD_H):
        for x in range(BOARD_W):
            if b.own_cells[b.idx(x, y)] == EMPTY:
                return x, y
    raise AssertionError(f"no EMPTY cell on board {player}")


def _snap(app: BattleshipApp, name: str) -> None:
    path = OUT / f"playtest_{name}.svg"
    try:
        svg = app.export_screenshot(title=name)
        path.write_text(svg, encoding="utf-8")
    except Exception as e:
        print(f"[playtest] snapshot {name} failed: {e}", file=sys.stderr)


def main() -> int:
    print("[playtest] pty boot smoke …", end=" ", flush=True)
    ok = pty_boot_smoke()
    print("ok" if ok else "FAIL")
    if not ok:
        return 1

    print("[playtest] driven walkthrough …")
    errors = asyncio.run(_driven("walkthrough"))
    if errors:
        print(f"[playtest] {errors} assertion failure(s)")
        return errors
    print(f"[playtest] all checks passed — snapshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
