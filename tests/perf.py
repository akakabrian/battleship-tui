"""Performance benchmark for battleship-tui hot paths.

Times:
    - full render_line loop (what Textual does per frame)
    - random_fleet (placement stress)
    - ai_pick (heatmap + optimal)
    - state_snapshot (REST hot path)
    - full game vs-AI simulation (end-to-end stress)
"""

from __future__ import annotations

import asyncio
import time

from battleship_tui.engine import (
    ShotResult,
    new_game,
)


def bench_render_loop(iters: int = 50) -> None:
    from battleship_tui.app import BattleshipApp

    async def _run():
        app = BattleshipApp(mode="vs_ai", ai="heatmap", seed=42)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            # Place + start battle to get a realistic mixed state.
            app.action_random_fleet()
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            # Fire a few shots.
            for _ in range(5):
                await pilot.press("space")
                await pilot.press("right")
                await pilot.pause()
            board = app.boards_view
            t0 = time.perf_counter()
            for _ in range(iters):
                for y in range(13):  # caption + header + 10 rows + pad
                    board.render_line(y)
            elapsed = time.perf_counter() - t0
            avg_ms = 1000 * elapsed / iters
            print(f"  render_loop     {iters}×  →  {avg_ms:.2f} ms/frame "
                  f"({1000*elapsed:.0f} ms total)")

    asyncio.run(_run())


def bench_random_fleet(iters: int = 500) -> None:
    t0 = time.perf_counter()
    for _ in range(iters):
        g = new_game(seed=None)
        g.random_fleet(0)
        g.random_fleet(1)
    elapsed = time.perf_counter() - t0
    avg_us = 1_000_000 * elapsed / iters
    print(f"  random_fleet    {iters}×  →  {avg_us:.1f} µs/call")


def bench_ai_pick(ai: str, iters: int = 200) -> None:
    g = new_game(ai=ai, seed=99)
    g.random_fleet(0)
    g.random_fleet(1)
    g.start_battle()
    # Fire a few shots to create some tracking state.
    for (x, y) in [(0, 0), (5, 5), (9, 9), (3, 7), (8, 2)]:
        g.turn = 0
        g.fire(0, x, y)
    t0 = time.perf_counter()
    for _ in range(iters):
        g._pick_heatmap(0, g.boards[0].tracking_cells, g.boards[1]) \
            if ai == "heatmap" else \
            g._pick_optimal(0, g.boards[0].tracking_cells, g.boards[1])
    elapsed = time.perf_counter() - t0
    avg_us = 1_000_000 * elapsed / iters
    print(f"  ai_pick {ai:<10} {iters}×  →  {avg_us:.1f} µs/call")


def bench_snapshot(iters: int = 500) -> None:
    g = new_game(seed=42)
    g.random_fleet(0)
    g.random_fleet(1)
    g.start_battle()
    t0 = time.perf_counter()
    for _ in range(iters):
        g.state_snapshot()
    elapsed = time.perf_counter() - t0
    avg_us = 1_000_000 * elapsed / iters
    print(f"  snapshot        {iters}×  →  {avg_us:.1f} µs/call")


def bench_full_game(ai: str, iters: int = 20) -> None:
    """End-to-end vs-AI game — two AI players fire at each other."""
    total_shots = 0
    t0 = time.perf_counter()
    for _ in range(iters):
        g = new_game(ai=ai, seed=None)
        g.random_fleet(0)
        g.random_fleet(1)
        g.start_battle()
        turns = 0
        while g.phase.value == "battle" and turns < 250:
            if g.turn == 0:
                if ai == "heatmap":
                    x, y = g._pick_heatmap(0, g.boards[0].tracking_cells, g.boards[1])
                elif ai == "optimal":
                    x, y = g._pick_optimal(0, g.boards[0].tracking_cells, g.boards[1])
                else:
                    x, y = g._pick_random(g.boards[0].tracking_cells, g.boards[1])
                g.fire(0, x, y)
            else:
                g.ai_take_turn()
            turns += 1
        total_shots += len(g.shot_log)
    elapsed = time.perf_counter() - t0
    print(f"  full_game {ai:<10} {iters}× "
          f" →  {1000*elapsed/iters:.1f} ms/game, "
          f"~{total_shots/iters:.0f} shots/game")


def main() -> None:
    print("Battleship TUI — perf baseline\n")
    print("TUI render:")
    bench_render_loop(iters=40)
    print("\nEngine operations:")
    bench_random_fleet(iters=300)
    bench_ai_pick("heatmap", iters=100)
    bench_ai_pick("optimal", iters=100)
    bench_snapshot(iters=200)
    print("\nEnd-to-end (two AI players):")
    bench_full_game("random", iters=10)
    bench_full_game("heatmap", iters=10)
    bench_full_game("optimal", iters=10)


if __name__ == "__main__":
    main()
