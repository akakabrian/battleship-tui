"""Agent REST API QA — spins up the server on a free port, hits every
endpoint, asserts shape. Exit code = # failures.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from typing import Awaitable, Callable

import aiohttp

from battleship_tui.agent_api import AgentAPI, start_server
from battleship_tui.engine import new_game


@dataclass
class Scenario:
    name: str
    fn: Callable[[aiohttp.ClientSession, str], Awaitable[None]]


async def s_healthz(sess, base):
    async with sess.get(f"{base}/healthz") as r:
        assert r.status == 200
        j = await r.json()
        assert j["ok"] is True


async def s_state_full(sess, base):
    async with sess.get(f"{base}/state") as r:
        assert r.status == 200
        j = await r.json()
        for k in ("mode", "phase", "boards", "fleet_order"):
            assert k in j


async def s_state_viewer_masks(sess, base):
    async with sess.get(f"{base}/state/0") as r:
        assert r.status == 200
        j = await r.json()
        # Opponent ship kinds should be masked.
        for s in j["boards"][1]["ships"]:
            assert s["kind"] is None


async def s_new_game_resets(sess, base):
    async with sess.post(f"{base}/new_game",
                         json={"mode": "vs_ai", "ai": "random",
                               "seed": 7}) as r:
        assert r.status == 200
        j = await r.json()
        assert j["ok"] is True
        assert j["state"]["phase"] == "placement"


async def s_random_fleet_places(sess, base):
    async with sess.post(f"{base}/random_fleet",
                         json={"player": 0}) as r:
        assert r.status == 200
        j = await r.json()
        assert j["ok"] is True
        assert j["state"]["boards"][0]["ships_remaining"] == 5


async def s_place_ship(sess, base):
    # New game so a clean placement state.
    await sess.post(f"{base}/new_game", json={"mode": "vs_ai", "seed": 9})
    async with sess.post(f"{base}/place",
                         json={"player": 0, "kind": "carrier",
                               "x": 0, "y": 0, "horizontal": True}) as r:
        assert r.status == 200
        j = await r.json()
        assert j["ok"] is True
        assert j["result"] == "ok"


async def s_place_invalid(sess, base):
    # Out of bounds.
    await sess.post(f"{base}/new_game", json={"mode": "vs_ai", "seed": 11})
    async with sess.post(f"{base}/place",
                         json={"player": 0, "kind": "carrier",
                               "x": 6, "y": 0, "horizontal": True}) as r:
        assert r.status == 400
        j = await r.json()
        assert j["result"] == "out_of_bounds"


async def s_start_battle_requires_all_placed(sess, base):
    await sess.post(f"{base}/new_game", json={"mode": "vs_ai", "seed": 13})
    # Only half-placed.
    async with sess.post(f"{base}/start_battle") as r:
        assert r.status == 400


async def s_fire_after_start(sess, base):
    await sess.post(f"{base}/new_game", json={"mode": "vs_ai", "seed": 15})
    await sess.post(f"{base}/random_fleet", json={"player": 0})
    await sess.post(f"{base}/start_battle")
    async with sess.post(f"{base}/fire",
                         json={"player": 0, "x": 0, "y": 0}) as r:
        assert r.status == 200
        j = await r.json()
        assert j["result"] in ("miss", "hit", "sunk", "win")


async def s_ai_turn(sess, base):
    await sess.post(f"{base}/new_game", json={"mode": "vs_ai", "seed": 17})
    await sess.post(f"{base}/random_fleet", json={"player": 0})
    await sess.post(f"{base}/start_battle")
    # Human fires first.
    await sess.post(f"{base}/fire", json={"player": 0, "x": 5, "y": 5})
    # Now AI turn.
    async with sess.post(f"{base}/ai_turn") as r:
        assert r.status == 200
        j = await r.json()
        assert j["ok"] is True
        assert len(j["results"]) >= 1


SCENARIOS: list[Scenario] = [
    Scenario("healthz", s_healthz),
    Scenario("state_full", s_state_full),
    Scenario("state_viewer_masks", s_state_viewer_masks),
    Scenario("new_game_resets", s_new_game_resets),
    Scenario("random_fleet_places", s_random_fleet_places),
    Scenario("place_ship", s_place_ship),
    Scenario("place_invalid", s_place_invalid),
    Scenario("start_battle_requires_all_placed", s_start_battle_requires_all_placed),
    Scenario("fire_after_start", s_fire_after_start),
    Scenario("ai_turn", s_ai_turn),
]


async def main() -> int:
    # Start the server on a free port.
    g = new_game(mode="vs_ai", ai="heatmap", seed=99)
    g.random_fleet(1)
    api = AgentAPI(g)
    runner, port = await start_server(api, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{port}"
    failures: list[tuple[str, str]] = []
    try:
        async with aiohttp.ClientSession() as sess:
            for scn in SCENARIOS:
                try:
                    await scn.fn(sess, base)
                    print(f"  [PASS] {scn.name}")
                except AssertionError as e:
                    print(f"  [FAIL] {scn.name}  -- AssertionError: {e}")
                    failures.append((scn.name, f"AssertionError: {e}"))
                except Exception as e:
                    tb = traceback.format_exc()
                    print(f"  [FAIL] {scn.name}  -- {type(e).__name__}: {e}")
                    failures.append((scn.name, tb))
    finally:
        await runner.cleanup()
    print()
    if failures:
        print(f"{len(failures)}/{len(SCENARIOS)} failed")
        for name, msg in failures:
            print(f"--- {name} ---\n{msg}\n")
        return len(failures)
    print(f"all {len(SCENARIOS)} API scenarios passed")
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
