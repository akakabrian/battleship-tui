"""Agent REST API for battleship-tui.

    POST /new_game   {mode?, ai?, salvo?, seed?}
    POST /place      {player, kind, x, y, horizontal}
    POST /random_fleet {player}
    POST /start_battle
    POST /fire       {player, x, y}
    POST /ai_turn                 → runs one AI turn (vs_ai only)
    GET  /state                   → state_snapshot(viewer=None)
    GET  /state/{player}          → state_snapshot(viewer=player)
    GET  /healthz                 → {"ok": true}
"""

from __future__ import annotations

import asyncio
from typing import Callable

try:
    from aiohttp import web
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "aiohttp is required for the agent API. "
        "Install with: pip install -e '.[agent]'"
    ) from e

from .engine import (
    Game,
    PlaceResult,
    ShipKind,
    ShotResult,
    new_game,
)


class AgentAPI:
    def __init__(self, game: Game,
                 on_change: Callable[[], None] | None = None) -> None:
        self._game = game
        self._on_change = on_change

    @property
    def game(self) -> Game:
        return self._game

    def set_game(self, game: Game) -> None:
        self._game = game

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass

    async def _state(self, req: web.Request) -> web.Response:
        return web.json_response(self._game.state_snapshot(viewer=None))

    async def _state_viewer(self, req: web.Request) -> web.Response:
        try:
            p = int(req.match_info["player"])
        except (KeyError, ValueError):
            return web.json_response({"error": "bad player"}, status=400)
        if p not in (0, 1):
            return web.json_response({"error": "player must be 0 or 1"}, status=400)
        return web.json_response(self._game.state_snapshot(viewer=p))

    async def _healthz(self, _req: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _new_game(self, req: web.Request) -> web.Response:
        try:
            data = await req.json()
        except Exception:
            data = {}
        mode = str(data.get("mode", "vs_ai"))
        ai = str(data.get("ai", "heatmap"))
        salvo = bool(data.get("salvo", False))
        seed = data.get("seed")
        try:
            g = new_game(mode=mode, ai=ai, salvo=salvo, seed=seed)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        self._game = g
        if mode == "vs_ai":
            self._game.random_fleet(1)
        self._notify()
        return web.json_response({"ok": True, "state": g.state_snapshot()})

    async def _place(self, req: web.Request) -> web.Response:
        try:
            data = await req.json()
            player = int(data["player"])
            kind_name = str(data["kind"]).upper()
            x = int(data["x"])
            y = int(data["y"])
            horizontal = bool(data["horizontal"])
        except Exception:
            return web.json_response(
                {"error": "expected {player, kind, x, y, horizontal}"},
                status=400,
            )
        try:
            kind = ShipKind[kind_name]
        except KeyError:
            return web.json_response(
                {"error": f"unknown kind: {kind_name!r}"}, status=400,
            )
        if player not in (0, 1):
            return web.json_response({"error": "player must be 0 or 1"}, status=400)
        r = self._game.place_ship(player, kind, x, y, horizontal)
        self._notify()
        return web.json_response(
            {"ok": r is PlaceResult.OK, "result": r.value,
             "state": self._game.state_snapshot()},
            status=200 if r is PlaceResult.OK else 400,
        )

    async def _random_fleet(self, req: web.Request) -> web.Response:
        try:
            data = await req.json()
            player = int(data["player"])
        except Exception:
            return web.json_response({"error": "expected {player}"}, status=400)
        if player not in (0, 1):
            return web.json_response({"error": "player must be 0 or 1"}, status=400)
        self._game.random_fleet(player)
        self._notify()
        return web.json_response(
            {"ok": True, "state": self._game.state_snapshot()},
        )

    async def _start_battle(self, _req: web.Request) -> web.Response:
        ok = self._game.start_battle()
        self._notify()
        return web.json_response(
            {"ok": ok, "state": self._game.state_snapshot()},
            status=200 if ok else 400,
        )

    async def _fire(self, req: web.Request) -> web.Response:
        try:
            data = await req.json()
            player = int(data["player"])
            x = int(data["x"])
            y = int(data["y"])
        except Exception:
            return web.json_response(
                {"error": "expected {player, x, y}"}, status=400,
            )
        r = self._game.fire(player, x, y)
        self._notify()
        return web.json_response(
            {"ok": r is not ShotResult.INVALID, "result": r.value,
             "state": self._game.state_snapshot()},
            status=200 if r is not ShotResult.INVALID else 400,
        )

    async def _ai_turn(self, _req: web.Request) -> web.Response:
        results = self._game.ai_take_turn()
        self._notify()
        return web.json_response(
            {"ok": True, "results": [r.value for r in results],
             "state": self._game.state_snapshot()},
        )

    def make_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/state", self._state)
        app.router.add_get("/state/{player}", self._state_viewer)
        app.router.add_get("/healthz", self._healthz)
        app.router.add_post("/new_game", self._new_game)
        app.router.add_post("/place", self._place)
        app.router.add_post("/random_fleet", self._random_fleet)
        app.router.add_post("/start_battle", self._start_battle)
        app.router.add_post("/fire", self._fire)
        app.router.add_post("/ai_turn", self._ai_turn)
        return app


async def start_server(api: AgentAPI, host: str = "127.0.0.1",
                       port: int = 8765) -> tuple[web.AppRunner, int]:
    aio_app = api.make_app()
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    bound_port = port
    server = getattr(site, "_server", None)
    sockets = getattr(server, "sockets", None) if server is not None else None
    if sockets:
        bound_port = sockets[0].getsockname()[1]
    return runner, bound_port


async def run_headless(mode: str = "vs_ai", *, ai: str = "heatmap",
                       salvo: bool = False, seed: int | None = None,
                       host: str = "127.0.0.1", port: int = 8765) -> None:
    g = new_game(mode=mode, ai=ai, salvo=salvo, seed=seed)
    if mode == "vs_ai":
        g.random_fleet(1)
    api = AgentAPI(g)
    runner, bound = await start_server(api, host=host, port=port)
    print(f"battleship-tui agent API listening on http://{host}:{bound}")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
