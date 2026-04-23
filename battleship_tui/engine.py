"""Pure-Python Battleship engine.

Design contract (mirrors what a SWIG-wrapped native engine would expose):

    from battleship_tui.engine import new_game
    g = new_game(mode="vs_ai", ai="heatmap", salvo=False, seed=42)
    g.random_fleet(player=0)            # auto-place for a side
    g.place_ship(player=0, kind=ShipKind.DESTROYER, x=0, y=0,
                 horizontal=True)        # manual placement
    g.start_battle()                    # all fleets placed → BATTLE phase
    g.fire(player=0, x=3, y=4)          # returns ShotResult
    g.ai_take_turn()                    # AI side plays; returns list[ShotResult]
    g.state_snapshot()                  # JSON-safe, fed to the REST API

State machine:
    PLACEMENT → each player places their 5 ships.
    BATTLE    → players alternate firing shots.
    OVER      → one side has sunk all opponent ships.

The engine never touches I/O. Timing lives in the App — engine is pure.
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field


# -------- board dimensions --------

BOARD_W = 10
BOARD_H = 10


# -------- ship kinds --------

class ShipKind(enum.Enum):
    CARRIER = ("Carrier",    5)
    BATTLESHIP = ("Battleship", 4)
    CRUISER = ("Cruiser",    3)
    SUBMARINE = ("Submarine",  3)
    DESTROYER = ("Destroyer",  2)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def length(self) -> int:
        return self.value[1]


# Canonical placement order (largest first — makes random-fleet termination
# reliable, and the UI reads top-to-bottom biggest-to-smallest).
FLEET_ORDER: tuple[ShipKind, ...] = (
    ShipKind.CARRIER,
    ShipKind.BATTLESHIP,
    ShipKind.CRUISER,
    ShipKind.SUBMARINE,
    ShipKind.DESTROYER,
)
FLEET_SIZE = sum(s.length for s in FLEET_ORDER)  # 17 cells


# -------- phase + result enums --------

class Phase(enum.Enum):
    PLACEMENT = "placement"
    BATTLE = "battle"
    OVER = "over"


class ShotResult(enum.Enum):
    MISS = "miss"
    HIT = "hit"
    SUNK = "sunk"
    WIN = "win"      # SUNK that took the opponent's last ship down
    INVALID = "invalid"


class PlaceResult(enum.Enum):
    OK = "ok"
    OUT_OF_BOUNDS = "out_of_bounds"
    OVERLAP = "overlap"
    ALREADY_PLACED = "already_placed"
    WRONG_PHASE = "wrong_phase"


# -------- cell state (per-board) --------
# Per player we maintain two logical views:
#   - own board: ship layout + shots taken against you (HIT/MISS overlay)
#   - tracking board: your shots at opponent — MISS or HIT known only via fire()

# Codes stored in the own-board array:
EMPTY = 0        # water, not shot at
MISS = 1         # opponent shot here and missed (water)
SHIP = 2         # a ship cell, not yet hit
HIT = 3          # ship cell that's been hit

# Codes stored in the tracking-board array:
#   UNKNOWN — you haven't fired here
#   TRACK_MISS — you fired and missed
#   TRACK_HIT — you fired and hit (possibly sunk — see sunk-ship set)
UNKNOWN = 0
TRACK_MISS = 1
TRACK_HIT = 2


# -------- data classes --------

@dataclass(eq=False)
class Ship:
    """A placed ship. `eq=False` because we store ships in lists and use
    identity-based operations (`ship in list`, `list.remove(ship)`) — two
    different ships can happen to share kind + length + orientation after
    respawn and we'd hit the wrong one (see skill's dataclass gotcha)."""
    kind: ShipKind
    x: int
    y: int
    horizontal: bool
    hits: set[tuple[int, int]] = field(default_factory=set)

    def cells(self) -> list[tuple[int, int]]:
        if self.horizontal:
            return [(self.x + i, self.y) for i in range(self.kind.length)]
        return [(self.x, self.y + i) for i in range(self.kind.length)]

    @property
    def length(self) -> int:
        return self.kind.length

    @property
    def is_sunk(self) -> bool:
        return len(self.hits) == self.kind.length


@dataclass(eq=False)
class Board:
    """One player's board + fleet. Shot-outcomes land on `own_cells` as
    the opponent fires at us; `tracking_cells` records what we've fired
    at the opponent."""
    width: int = BOARD_W
    height: int = BOARD_H
    own_cells: list[int] = field(default_factory=list)
    tracking_cells: list[int] = field(default_factory=list)
    ships: list[Ship] = field(default_factory=list)
    # Sunk ships observed on the tracking board — set of cell coords so we
    # can render a "ship outline" style for the shooter. (Only tells us
    # which cells are part of a sunk enemy ship, not its kind identity.)
    tracking_sunk_cells: set[tuple[int, int]] = field(default_factory=set)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def idx(self, x: int, y: int) -> int:
        return y * self.width + x

    @property
    def placed_count(self) -> int:
        return len(self.ships)

    @property
    def all_placed(self) -> bool:
        return self.placed_count == len(FLEET_ORDER)

    @property
    def ships_remaining(self) -> int:
        return sum(1 for s in self.ships if not s.is_sunk)

    @property
    def hits_taken(self) -> int:
        return sum(1 for c in self.own_cells if c == HIT)

    @property
    def fleet_sunk(self) -> bool:
        return bool(self.ships) and all(s.is_sunk for s in self.ships)

    def ship_at(self, x: int, y: int) -> Ship | None:
        for s in self.ships:
            if (x, y) in s.cells():
                return s
        return None


# -------- the Game --------

@dataclass
class Game:
    mode: str = "vs_ai"          # "hotseat" | "vs_ai"
    ai: str = "heatmap"          # "random" | "heatmap" | "optimal"
    salvo: bool = False
    boards: list[Board] = field(default_factory=list)
    phase: Phase = Phase.PLACEMENT
    turn: int = 0                # whose turn to fire — 0 or 1
    winner: int | None = None
    # Which ship the current placer is about to place (per player index).
    next_to_place: list[int] = field(default_factory=lambda: [0, 0])
    # Ordered log of every shot for replay / agent visibility.
    shot_log: list[dict] = field(default_factory=list)
    # AI memory (per opponent board view index).
    _ai_state: dict = field(default_factory=dict)
    _rng: random.Random = field(default_factory=random.Random)

    # --- placement ---

    def place_ship(self, player: int, kind: ShipKind, x: int, y: int,
                   horizontal: bool) -> PlaceResult:
        if self.phase is not Phase.PLACEMENT:
            return PlaceResult.WRONG_PHASE
        board = self.boards[player]
        # Already placed this kind?
        for s in board.ships:
            if s.kind is kind:
                return PlaceResult.ALREADY_PLACED
        # Bounds check.
        length = kind.length
        if horizontal:
            if x < 0 or x + length > board.width or y < 0 or y >= board.height:
                return PlaceResult.OUT_OF_BOUNDS
        else:
            if x < 0 or x >= board.width or y < 0 or y + length > board.height:
                return PlaceResult.OUT_OF_BOUNDS
        # Overlap check.
        ship = Ship(kind=kind, x=x, y=y, horizontal=horizontal)
        cells = ship.cells()
        for cx, cy in cells:
            if board.own_cells[board.idx(cx, cy)] != EMPTY:
                return PlaceResult.OVERLAP
        # Commit.
        for cx, cy in cells:
            board.own_cells[board.idx(cx, cy)] = SHIP
        board.ships.append(ship)
        # Advance the "next to place" cursor for UIs that step kinds in
        # FLEET_ORDER. If the player placed out of order, this still
        # advances monotonically through kinds they haven't placed yet.
        self._advance_next_to_place(player)
        return PlaceResult.OK

    def _advance_next_to_place(self, player: int) -> None:
        placed = {s.kind for s in self.boards[player].ships}
        for i, k in enumerate(FLEET_ORDER):
            if k not in placed:
                self.next_to_place[player] = i
                return
        self.next_to_place[player] = len(FLEET_ORDER)  # all placed

    def unplace_last(self, player: int) -> bool:
        """Undo the most recently placed ship for this player (placement phase)."""
        if self.phase is not Phase.PLACEMENT:
            return False
        board = self.boards[player]
        if not board.ships:
            return False
        ship = board.ships.pop()
        for cx, cy in ship.cells():
            board.own_cells[board.idx(cx, cy)] = EMPTY
        self._advance_next_to_place(player)
        return True

    def random_fleet(self, player: int) -> None:
        """Clear + auto-place a full fleet for this player, respecting
        bounds + no-overlap."""
        # Clear existing.
        board = self.boards[player]
        board.ships.clear()
        board.own_cells = [EMPTY] * (board.width * board.height)
        for kind in FLEET_ORDER:
            self._random_place_one(player, kind)
        self._advance_next_to_place(player)

    def _random_place_one(self, player: int, kind: ShipKind,
                          max_attempts: int = 500) -> None:
        board = self.boards[player]
        for _ in range(max_attempts):
            horizontal = self._rng.random() < 0.5
            if horizontal:
                x = self._rng.randrange(0, board.width - kind.length + 1)
                y = self._rng.randrange(0, board.height)
            else:
                x = self._rng.randrange(0, board.width)
                y = self._rng.randrange(0, board.height - kind.length + 1)
            if self.place_ship(player, kind, x, y, horizontal) is PlaceResult.OK:
                return
        # Pathological — give up. Shouldn't happen on a 10x10 with our fleet.
        raise RuntimeError(f"Could not place {kind.label} after {max_attempts} tries")

    def start_battle(self) -> bool:
        """Flip from PLACEMENT to BATTLE. Both boards must be fully placed."""
        if self.phase is not Phase.PLACEMENT:
            return False
        if not all(b.all_placed for b in self.boards):
            return False
        self.phase = Phase.BATTLE
        self.turn = 0
        return True

    # --- firing ---

    def fire(self, player: int, x: int, y: int) -> ShotResult:
        """Player `player` fires at opponent (1 - player) at (x, y)."""
        if self.phase is not Phase.BATTLE:
            return ShotResult.INVALID
        if player != self.turn:
            return ShotResult.INVALID
        opp = 1 - player
        my_tracking = self.boards[player].tracking_cells
        their_own = self.boards[opp].own_cells
        their_board = self.boards[opp]
        if not their_board.in_bounds(x, y):
            return ShotResult.INVALID
        idx = their_board.idx(x, y)
        if my_tracking[idx] != UNKNOWN:
            return ShotResult.INVALID
        cell = their_own[idx]
        result: ShotResult
        if cell == SHIP:
            their_own[idx] = HIT
            my_tracking[idx] = TRACK_HIT
            # Mark the hit on the specific ship.
            ship = their_board.ship_at(x, y)
            if ship is not None:
                ship.hits.add((x, y))
                if ship.is_sunk:
                    # Reveal sunk-ship outline on my tracking board.
                    for cx, cy in ship.cells():
                        self.boards[player].tracking_sunk_cells.add((cx, cy))
                    if their_board.fleet_sunk:
                        self.phase = Phase.OVER
                        self.winner = player
                        result = ShotResult.WIN
                    else:
                        result = ShotResult.SUNK
                else:
                    result = ShotResult.HIT
            else:
                result = ShotResult.HIT  # shouldn't happen — defensive
        elif cell == EMPTY:
            their_own[idx] = MISS
            my_tracking[idx] = TRACK_MISS
            result = ShotResult.MISS
        else:
            # Already HIT or MISS on their own board — shouldn't happen since
            # tracking blocks it, but defensive.
            return ShotResult.INVALID
        self.shot_log.append({
            "player": player, "x": x, "y": y,
            "result": result.value,
        })
        # Turn handoff — in classic mode, always pass turn.
        # In salvo mode, the caller queues multiple shots per volley and
        # calls `end_volley()` to pass turn; we leave turn alone here.
        if not self.salvo and result not in (ShotResult.WIN, ShotResult.INVALID):
            self.turn = 1 - self.turn
        return result

    def end_volley(self) -> None:
        """In salvo mode, caller invokes this after firing the volley to
        pass the turn. No-op in classic mode."""
        if self.phase is Phase.BATTLE and self.salvo:
            self.turn = 1 - self.turn

    def salvo_shots_this_turn(self, player: int) -> int:
        """How many shots the given player gets this volley in salvo mode.
        In classic mode, always 1."""
        if not self.salvo:
            return 1
        return max(1, self.boards[player].ships_remaining)

    # --- AI ---

    def ai_take_turn(self) -> list[ShotResult]:
        """Let the AI side play one turn (possibly multiple shots in salvo).
        Returns the list of shot results in order. No-op if it's not the
        AI's turn or we're not in BATTLE."""
        if self.phase is not Phase.BATTLE:
            return []
        if self.mode != "vs_ai":
            return []
        ai_player = 1  # player 0 is always human in vs_ai
        if self.turn != ai_player:
            return []
        shots = self.salvo_shots_this_turn(ai_player)
        results: list[ShotResult] = []
        for _ in range(shots):
            if self.phase is not Phase.BATTLE:
                break
            x, y = self._ai_pick(ai_player)
            r = self.fire(ai_player, x, y)
            results.append(r)
            if r is ShotResult.WIN:
                break
        if self.salvo:
            self.end_volley()
        return results

    def _ai_pick(self, player: int) -> tuple[int, int]:
        tracking = self.boards[player].tracking_cells
        opp = 1 - player
        opp_board = self.boards[opp]
        if self.ai == "random":
            return self._pick_random(tracking, opp_board)
        if self.ai == "heatmap":
            return self._pick_heatmap(player, tracking, opp_board)
        if self.ai == "optimal":
            return self._pick_optimal(player, tracking, opp_board)
        return self._pick_random(tracking, opp_board)

    def _pick_random(self, tracking: list[int], opp_board: Board) -> tuple[int, int]:
        candidates = [(x, y)
                      for y in range(opp_board.height)
                      for x in range(opp_board.width)
                      if tracking[opp_board.idx(x, y)] == UNKNOWN]
        return self._rng.choice(candidates)

    def _pick_heatmap(self, player: int, tracking: list[int],
                      opp_board: Board) -> tuple[int, int]:
        """Heatmap / hunt-and-target AI.
        - Hunt mode: compute a probability heatmap of how many remaining
          enemy ships could overlap each cell. Prefer parity-4 cells (since
          min-remaining-ship is usually 2).
        - Target mode: if we have hits that aren't part of a sunk ship,
          attack their 4-neighbours; extend along a discovered axis.
        """
        # 1. Collect unresolved hits (HIT cells not yet part of a known sunk ship).
        sunk = opp_board.tracking_sunk_cells  # revealed on our tracking board
        live_hits = [(x, y)
                     for y in range(opp_board.height)
                     for x in range(opp_board.width)
                     if tracking[opp_board.idx(x, y)] == TRACK_HIT
                     and (x, y) not in sunk]
        if live_hits:
            pick = self._target_from_hits(live_hits, tracking, opp_board)
            if pick is not None:
                return pick
        # 2. Hunt mode — heatmap of remaining ships.
        remaining_ships = self._remaining_ship_lengths(player)
        heat = self._build_heatmap(tracking, opp_board, remaining_ships)
        # Parity filter: ignore cells whose parity can't fit min-remaining.
        min_len = min(remaining_ships) if remaining_ships else 2
        best: tuple[int, int] | None = None
        best_score = -1
        for y in range(opp_board.height):
            for x in range(opp_board.width):
                if tracking[opp_board.idx(x, y)] != UNKNOWN:
                    continue
                score = heat[opp_board.idx(x, y)]
                # Parity bonus — cells where (x + y) % min_len == 0
                if (x + y) % min_len == 0:
                    score += 1
                if score > best_score:
                    best_score = score
                    best = (x, y)
        if best is None:
            return self._pick_random(tracking, opp_board)
        return best

    def _pick_optimal(self, player: int, tracking: list[int],
                      opp_board: Board) -> tuple[int, int]:
        """Like heatmap but fully constraint-aware — uses the same heatmap
        computation but without the parity hack, since the heatmap itself
        already encodes the exact number of feasible placements per cell."""
        sunk = opp_board.tracking_sunk_cells
        live_hits = [(x, y)
                     for y in range(opp_board.height)
                     for x in range(opp_board.width)
                     if tracking[opp_board.idx(x, y)] == TRACK_HIT
                     and (x, y) not in sunk]
        if live_hits:
            pick = self._target_from_hits(live_hits, tracking, opp_board)
            if pick is not None:
                return pick
        remaining_ships = self._remaining_ship_lengths(player)
        heat = self._build_heatmap(tracking, opp_board, remaining_ships)
        best: tuple[int, int] | None = None
        best_score = -1
        for y in range(opp_board.height):
            for x in range(opp_board.width):
                if tracking[opp_board.idx(x, y)] != UNKNOWN:
                    continue
                score = heat[opp_board.idx(x, y)]
                if score > best_score:
                    best_score = score
                    best = (x, y)
        if best is None:
            return self._pick_random(tracking, opp_board)
        return best

    def _remaining_ship_lengths(self, player: int) -> list[int]:
        """Which enemy ship lengths are still in play (not known-sunk)?
        We hold the full game state, so observe `is_sunk` directly rather
        than reconstructing from `tracking_sunk_cells` — same answer,
        cheaper."""
        opp = self.boards[1 - player]
        return [s.kind.length for s in opp.ships if not s.is_sunk]

    def _build_heatmap(self, tracking: list[int], opp_board: Board,
                       lengths: list[int]) -> list[int]:
        """For each cell, count how many (orientation, position) placements
        of any remaining ship length could fit, consistent with our current
        tracking info:
          - all cells the ship would occupy are UNKNOWN or TRACK_HIT,
          - at least one cell is UNKNOWN (don't double-count pure-hit lines),
          - ship doesn't go off-board.
        We give +weight for cells adjacent to TRACK_HIT to bias toward
        extending a discovered hit."""
        W, H = opp_board.width, opp_board.height
        heat = [0] * (W * H)
        for L in lengths:
            # Horizontal placements.
            for y in range(H):
                for x in range(W - L + 1):
                    valid = True
                    has_unknown = False
                    for i in range(L):
                        c = tracking[opp_board.idx(x + i, y)]
                        if c == TRACK_MISS:
                            valid = False
                            break
                        # TRACK_HIT on a known-sunk cell is off-limits
                        if c == TRACK_HIT and (x + i, y) in opp_board.tracking_sunk_cells:
                            valid = False
                            break
                        if c == UNKNOWN:
                            has_unknown = True
                    if valid and has_unknown:
                        for i in range(L):
                            if tracking[opp_board.idx(x + i, y)] == UNKNOWN:
                                heat[opp_board.idx(x + i, y)] += 1
            # Vertical placements.
            for x in range(W):
                for y in range(H - L + 1):
                    valid = True
                    has_unknown = False
                    for i in range(L):
                        c = tracking[opp_board.idx(x, y + i)]
                        if c == TRACK_MISS:
                            valid = False
                            break
                        if c == TRACK_HIT and (x, y + i) in opp_board.tracking_sunk_cells:
                            valid = False
                            break
                        if c == UNKNOWN:
                            has_unknown = True
                    if valid and has_unknown:
                        for i in range(L):
                            if tracking[opp_board.idx(x, y + i)] == UNKNOWN:
                                heat[opp_board.idx(x, y + i)] += 1
        return heat

    def _target_from_hits(self, live_hits: list[tuple[int, int]],
                          tracking: list[int], opp_board: Board,
                          ) -> tuple[int, int] | None:
        """Target mode — pick a cell adjacent to live (unsunk) hits.

        If 2+ hits are colinear, extend along the axis; otherwise fire at
        any unknown 4-neighbour of any hit."""
        hit_set = set(live_hits)
        W, H = opp_board.width, opp_board.height

        def ok(x: int, y: int) -> bool:
            return (0 <= x < W and 0 <= y < H
                    and tracking[opp_board.idx(x, y)] == UNKNOWN)

        # Look for a colinear pair with a valid extension.
        for x1, y1 in live_hits:
            for x2, y2 in live_hits:
                if (x1, y1) == (x2, y2):
                    continue
                # Horizontal collinear
                if y1 == y2 and abs(x1 - x2) >= 1:
                    mn, mx = min(x1, x2), max(x1, x2)
                    # Check all between are also hits.
                    if all((xi, y1) in hit_set for xi in range(mn, mx + 1)):
                        if ok(mn - 1, y1):
                            return (mn - 1, y1)
                        if ok(mx + 1, y1):
                            return (mx + 1, y1)
                # Vertical collinear
                if x1 == x2 and abs(y1 - y2) >= 1:
                    mn, mx = min(y1, y2), max(y1, y2)
                    if all((x1, yi) in hit_set for yi in range(mn, mx + 1)):
                        if ok(x1, mn - 1):
                            return (x1, mn - 1)
                        if ok(x1, mx + 1):
                            return (x1, mx + 1)
        # No colinear extension — pick any unknown 4-neighbour.
        candidates: list[tuple[int, int]] = []
        for x, y in live_hits:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if ok(nx, ny):
                    candidates.append((nx, ny))
        if candidates:
            return self._rng.choice(candidates)
        return None

    # --- snapshots ---

    def state_snapshot(self, viewer: int | None = None) -> dict:
        """JSON-safe snapshot.

        `viewer` selects whose perspective to show:
          - None: full-god view (includes both fleets) — used by tests + AI.
          - 0/1: hides opponent's ship layout — used by hotseat/API.
        """
        def _board_view(p: int, hide_opp: bool) -> dict:
            b = self.boards[p]
            opp_p = 1 - p
            opp = self.boards[opp_p]
            # Our own board reveal.
            own = [[_code_to_str(b.own_cells[b.idx(x, y)])
                    for x in range(b.width)]
                   for y in range(b.height)]
            # Our tracking board.
            track = [[_track_to_str(b.tracking_cells[b.idx(x, y)])
                      for x in range(b.width)]
                     for y in range(b.height)]
            ships = [
                {"kind": s.kind.name, "length": s.length, "x": s.x, "y": s.y,
                 "horizontal": s.horizontal, "sunk": s.is_sunk,
                 "hits": len(s.hits)}
                for s in b.ships
            ]
            view = {
                "own": own,
                "tracking": track,
                "ships": ships,
                "ships_remaining": b.ships_remaining,
                "hits_taken": b.hits_taken,
                "all_placed": b.all_placed,
                "sunk_cells_on_tracking": sorted(list(b.tracking_sunk_cells)),
            }
            return view

        if viewer is None:
            boards = [_board_view(0, False), _board_view(1, False)]
        else:
            boards = [
                _board_view(0, viewer != 0),
                _board_view(1, viewer != 1),
            ]
            # Mask opponent ships.
            opp = 1 - viewer
            boards[opp]["ships"] = [
                {"kind": None, "length": s["length"], "sunk": s["sunk"]}
                for s in boards[opp]["ships"]
            ]
            # Mask opponent's own-board SHIP cells (but leave HIT / MISS visible
            # — those are observable via your tracking board anyway, and showing
            # them on their side lets agents reconcile). Actually: in hotseat
            # the "opponent's own board" is their private view. Don't show
            # unhit ship positions.
            for y in range(BOARD_H):
                for x in range(BOARD_W):
                    if boards[opp]["own"][y][x] == "ship":
                        boards[opp]["own"][y][x] = "empty"

        return {
            "mode": self.mode,
            "ai": self.ai,
            "salvo": self.salvo,
            "phase": self.phase.value,
            "turn": self.turn,
            "winner": self.winner,
            "next_to_place": list(self.next_to_place),
            "fleet_order": [k.name for k in FLEET_ORDER],
            "boards": boards,
            "shot_count": len(self.shot_log),
        }


def _code_to_str(c: int) -> str:
    return {EMPTY: "empty", MISS: "miss", SHIP: "ship", HIT: "hit"}.get(c, "unknown")


def _track_to_str(c: int) -> str:
    return {UNKNOWN: "unknown", TRACK_MISS: "miss", TRACK_HIT: "hit"}.get(c, "unknown")


# -------- factory --------

def new_game(mode: str = "vs_ai", *, ai: str = "heatmap",
             salvo: bool = False, seed: int | None = None) -> Game:
    if mode not in ("hotseat", "vs_ai"):
        raise ValueError(f"unknown mode: {mode!r}")
    if ai not in ("random", "heatmap", "optimal"):
        raise ValueError(f"unknown ai: {ai!r}")
    g = Game(mode=mode, ai=ai, salvo=salvo)
    g.boards = [
        Board(own_cells=[EMPTY] * (BOARD_W * BOARD_H),
              tracking_cells=[UNKNOWN] * (BOARD_W * BOARD_H)),
        Board(own_cells=[EMPTY] * (BOARD_W * BOARD_H),
              tracking_cells=[UNKNOWN] * (BOARD_W * BOARD_H)),
    ]
    if seed is not None:
        g._rng = random.Random(seed)
    return g
