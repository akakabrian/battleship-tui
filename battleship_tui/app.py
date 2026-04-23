"""Battleship TUI — Textual App, BoardsView, side panels."""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, RichLog, Static

from . import tiles
from .engine import (
    BOARD_H,
    BOARD_W,
    EMPTY,
    FLEET_ORDER,
    Game,
    HIT,
    MISS,
    Phase,
    PlaceResult,
    SHIP,
    ShotResult,
    TRACK_HIT,
    TRACK_MISS,
    UNKNOWN,
    new_game,
)
from .screens import (
    HelpScreen,
    LegendScreen,
    PassBoardScreen,
    ResultScreen,
)
from .sounds import SoundBoard


# Each cell rendered as 3 char columns wide × 1 row tall (glyph + spacing).
CELL_W = 3
CELL_H = 1

# Row/column label widths.
LABEL_LEFT = 3   # "10 " or " 1 "
LABEL_TOP = 1    # one label row

# Width of one board including labels = LABEL_LEFT + BOARD_W * CELL_W.
ONE_BOARD_W = LABEL_LEFT + BOARD_W * CELL_W

# Separator column between the two boards.
BOARD_GAP = 3

# Total virtual width/height of the dual-board widget.
DUAL_W = 2 * ONE_BOARD_W + BOARD_GAP
DUAL_H = LABEL_TOP + BOARD_H * CELL_H + 1  # +1 for board caption row above


class BoardsView(ScrollView):
    """Renders the two 10x10 boards side-by-side with row/col labels.

    Left board  = active player's own fleet view
    Right board = active player's tracking view of the opponent

    During PLACEMENT, only the active player's own board is meaningful; the
    tracking board is just a placeholder showing "PLACE SHIPS FIRST".
    """

    DEFAULT_CSS = "BoardsView { padding: 0; }"

    cursor_x: reactive[int] = reactive(0)
    cursor_y: reactive[int] = reactive(0)
    # Which board the cursor is on: 0 = own (placement), 1 = tracking (fire).
    # During PLACEMENT we lock to 0; during BATTLE we lock to 1.
    cursor_board: reactive[int] = reactive(0)
    # Placement ghost orientation: True = horizontal.
    placement_horizontal: reactive[bool] = reactive(True)

    class CellAction(Message):
        def __init__(self, board: int, x: int, y: int, action: str) -> None:
            self.board = board
            self.x = x
            self.y = y
            self.action = action
            super().__init__()

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.active_player = 0
        self.cursor_x = 0
        self.cursor_y = 0
        self._update_virtual_size()

    def attach_game(self, game: Game, active_player: int = 0) -> None:
        self.game = game
        self.active_player = active_player
        self.cursor_x = 0
        self.cursor_y = 0
        self._update_virtual_size()
        self.refresh()

    def set_active_player(self, p: int) -> None:
        self.active_player = p
        self.refresh()

    def _update_virtual_size(self) -> None:
        self.virtual_size = Size(DUAL_W, DUAL_H)

    def watch_cursor_x(self, old: int, new: int) -> None:
        self._refresh_board(self.cursor_board)

    def watch_cursor_y(self, old: int, new: int) -> None:
        self._refresh_board(self.cursor_board)

    def watch_placement_horizontal(self, old: bool, new: bool) -> None:
        # Rotating the ghost can change which cells the preview covers.
        self._refresh_board(0)

    def watch_cursor_board(self, old: int, new: int) -> None:
        self.refresh()

    def _refresh_board(self, board: int) -> None:
        if not self.is_mounted:
            return
        # Repaint the entire widget; it's small (~11 rows) and this keeps
        # the ghost/cursor math simple.
        self.refresh()

    # --- rendering ---

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        world_row = y + scroll_y
        visible_w = self.size.width
        segments: list[Segment] = []

        if world_row == 0:
            # Caption row: "YOUR FLEET" and "TARGETING" over each board.
            left_caption = self._caption_for_board(0)
            right_caption = self._caption_for_board(1)
            s = (" " * LABEL_LEFT
                 + _center(left_caption, BOARD_W * CELL_W)
                 + " " * BOARD_GAP
                 + " " * LABEL_LEFT
                 + _center(right_caption, BOARD_W * CELL_W))
            segments.append(Segment(s, tiles.label_style()))
            return self._pad_strip(segments, visible_w)

        if world_row == 1:
            # Column header row — "A B C D E F G H I J" for each board.
            headers = ""
            for b in range(2):
                headers += " " * LABEL_LEFT
                for x in range(BOARD_W):
                    headers += f" {chr(ord('A') + x)} "
                if b == 0:
                    headers += " " * BOARD_GAP
            segments.append(Segment(headers, tiles.label_style()))
            return self._pad_strip(segments, visible_w)

        # Board row (cells).
        board_y = world_row - 2
        if board_y < 0 or board_y >= BOARD_H:
            return Strip.blank(visible_w)

        for b in range(2):
            # Row label — right-aligned 2-digit row number + space.
            row_label = f"{board_y + 1:>2} "
            segments.append(Segment(row_label, tiles.label_style()))
            for x in range(BOARD_W):
                glyph, style = self._cell_on_board(b, x, board_y)
                cell_str = f" {glyph} "
                segments.append(Segment(cell_str, style))
            if b == 0:
                segments.append(Segment(" " * BOARD_GAP, Style(bgcolor="#0a0a0c")))

        return self._pad_strip(segments, visible_w)

    def _pad_strip(self, segments: list[Segment], visible_w: int) -> Strip:
        painted = sum(len(s.text) for s in segments)
        if painted < visible_w:
            segments.append(Segment(" " * (visible_w - painted),
                                    Style(bgcolor="#0a0a0c")))
        return Strip(segments)

    def _caption_for_board(self, board: int) -> str:
        if self.game.phase is Phase.PLACEMENT:
            if board == 0:
                return "YOUR FLEET — place ships"
            return "(targeting unlocks in battle)"
        if self.game.phase is Phase.OVER:
            return "YOUR FLEET" if board == 0 else "TARGETING (final)"
        # BATTLE
        return "YOUR FLEET" if board == 0 else "TARGETING"

    def _cell_on_board(self, board: int, x: int, y: int) -> tuple[str, Style]:
        """Resolve the glyph + Style for board `board` at (x, y)."""
        at_cursor = (self.cursor_board == board
                     and self.cursor_x == x and self.cursor_y == y)

        if board == 0:
            return self._own_cell(x, y, at_cursor)
        return self._track_cell(x, y, at_cursor)

    def _own_cell(self, x: int, y: int, at_cursor: bool) -> tuple[str, Style]:
        b = self.game.boards[self.active_player]
        code = b.own_cells[b.idx(x, y)]

        # Placement ghost: overlay a preview of where the current ship would land.
        if self.game.phase is Phase.PLACEMENT:
            ghost = self._ghost_cells()
            if ghost is not None and (x, y) in ghost[0]:
                valid = ghost[1]
                return tiles.GLYPH_GHOST_OK if valid else tiles.GLYPH_GHOST_BAD, \
                    tiles.ghost_style(x, y, valid, cursor=at_cursor)

        if code == HIT:
            return tiles.GLYPH_HIT_OWN, tiles.hit_style(x, y, cursor=at_cursor)
        if code == MISS:
            return tiles.GLYPH_MISS_OWN, tiles.miss_style(x, y, cursor=at_cursor)
        if code == SHIP:
            return tiles.GLYPH_SHIP, tiles.ship_style(x, y, cursor=at_cursor)
        # EMPTY
        return tiles.GLYPH_WATER, tiles.water_style(x, y, cursor=at_cursor)

    def _track_cell(self, x: int, y: int, at_cursor: bool) -> tuple[str, Style]:
        b = self.game.boards[self.active_player]
        code = b.tracking_cells[b.idx(x, y)]
        if code == TRACK_HIT:
            if (x, y) in b.tracking_sunk_cells:
                return tiles.GLYPH_SUNK_OUTLINE, tiles.sunk_style(x, y, cursor=at_cursor)
            return tiles.GLYPH_HIT_TRACK, tiles.hit_style(x, y, cursor=at_cursor)
        if code == TRACK_MISS:
            return tiles.GLYPH_MISS_TRACK, tiles.miss_style(x, y, cursor=at_cursor)
        # UNKNOWN
        return tiles.GLYPH_UNKNOWN, tiles.water_style(x, y, cursor=at_cursor)

    def _ghost_cells(self) -> tuple[set[tuple[int, int]], bool] | None:
        """Cells the current placement ghost would occupy, plus validity."""
        if self.game.phase is not Phase.PLACEMENT:
            return None
        idx = self.game.next_to_place[self.active_player]
        if idx >= len(FLEET_ORDER):
            return None  # all placed
        kind = FLEET_ORDER[idx]
        length = kind.length
        hx, hy = self.cursor_x, self.cursor_y
        horizontal = self.placement_horizontal
        if horizontal:
            cells = {(hx + i, hy) for i in range(length)}
        else:
            cells = {(hx, hy + i) for i in range(length)}
        # Validity.
        b = self.game.boards[self.active_player]
        valid = True
        for cx, cy in cells:
            if not (0 <= cx < b.width and 0 <= cy < b.height):
                valid = False
                break
            if b.own_cells[b.idx(cx, cy)] != EMPTY:
                valid = False
                break
        return (cells, valid)

    # --- mouse ---

    def _event_to_tile(self, event) -> tuple[int, int, int] | None:
        """Return (board, x, y) or None if the click missed the grid."""
        x = event.x + int(self.scroll_offset.x)
        y = event.y + int(self.scroll_offset.y)
        # Subtract the caption + header rows.
        board_y = y - 2
        if board_y < 0 or board_y >= BOARD_H:
            return None
        # First board runs [LABEL_LEFT .. LABEL_LEFT + BOARD_W*CELL_W)
        # Second board starts after BOARD_GAP + LABEL_LEFT.
        left_start = LABEL_LEFT
        left_end = LABEL_LEFT + BOARD_W * CELL_W
        right_start = left_end + BOARD_GAP + LABEL_LEFT
        right_end = right_start + BOARD_W * CELL_W
        if left_start <= x < left_end:
            tx = (x - left_start) // CELL_W
            return (0, tx, board_y)
        if right_start <= x < right_end:
            tx = (x - right_start) // CELL_W
            return (1, tx, board_y)
        return None

    async def on_click(self, event: events.Click) -> None:
        spot = self._event_to_tile(event)
        if spot is None:
            return
        board, tx, ty = spot
        # Click the inactive board = switch cursor to it (no action).
        if board != self.cursor_board:
            # Only allow switching if the phase permits clicking that board.
            if self.game.phase is Phase.PLACEMENT and board == 1:
                return
            if self.game.phase is Phase.BATTLE and board == 0:
                # Allowed to look at own board but no action.
                self.cursor_board = board
        else:
            self.cursor_board = board
        self.cursor_x = tx
        self.cursor_y = ty
        # Generate an action message.
        if self.game.phase is Phase.PLACEMENT and board == 0:
            self.post_message(self.CellAction(board, tx, ty, "place"))
        elif self.game.phase is Phase.BATTLE and board == 1:
            self.post_message(self.CellAction(board, tx, ty, "fire"))


def _center(text: str, width: int) -> str:
    if len(text) >= width:
        return text[:width]
    pad = width - len(text)
    left = pad // 2
    right = pad - left
    return " " * left + text + " " * right


# -------- side panels --------

class StatusPanel(Static):
    def __init__(self) -> None:
        super().__init__("", id="status")
        self.border_title = "Status"

    def refresh_panel(self, app: "BattleshipApp") -> None:
        g = app.game
        if g.phase is Phase.PLACEMENT:
            idx = g.next_to_place[app.boards_view.active_player]
            if idx < len(FLEET_ORDER):
                kind = FLEET_ORDER[idx]
                ship_line = f"  Placing: [bold]{kind.label}[/] ({kind.length})"
            else:
                ship_line = "  [bold rgb(80,220,110)]Fleet complete![/]"
            orient = "H" if app.boards_view.placement_horizontal else "V"
            lines = [
                f"  [bold]Player {app.boards_view.active_player + 1}[/] — [bold]PLACEMENT[/]",
                "",
                ship_line,
                f"  Orientation: [bold]{orient}[/]    [dim](r to rotate)[/]",
                f"  Placed: [bold]{g.boards[app.boards_view.active_player].placed_count}[/]/5",
                "",
                "  [bold]R[/]  random fleet",
                "  [bold]u[/]  undo last",
                "  [bold]Space/Enter[/]  place",
                "  [bold]Tab[/]  finish → battle",
            ]
        elif g.phase is Phase.BATTLE:
            turn_label = "YOUR TURN" if g.turn == 0 else "ENEMY TURN"
            if g.mode == "hotseat":
                turn_label = f"PLAYER {g.turn + 1}"
            shots = g.salvo_shots_this_turn(g.turn)
            lines = [
                f"  [bold]{turn_label}[/]",
                "",
                f"  Mode:   [bold]{g.mode}[/]",
                f"  AI:     [bold]{g.ai}[/]" if g.mode == "vs_ai" else "",
                f"  Salvo:  [bold]{'on' if g.salvo else 'off'}[/]",
                "",
                f"  Your fleet:  [bold]{g.boards[0].ships_remaining}[/]/5",
                f"  Enemy fleet: [bold]{g.boards[1].ships_remaining}[/]/5",
                "",
                f"  Shots this volley: [bold]{shots}[/]" if g.salvo else "",
                f"  Total shots: [dim]{len(g.shot_log)}[/]",
            ]
            lines = [l for l in lines if l != ""]
        else:  # OVER
            winner = (g.winner or 0) + 1
            lines = [
                f"  [bold rgb(245,190,80)]★ Player {winner} wins ★[/]",
                "",
                f"  Total shots: [bold]{len(g.shot_log)}[/]",
                "",
                "  [bold]n[/]  new game",
                "  [bold]q[/]  quit",
            ]
        self.update("\n".join(lines))


class FleetPanel(Static):
    """Shows the active player's fleet roster with sunk/alive status."""
    def __init__(self) -> None:
        super().__init__("", id="fleet")
        self.border_title = "Fleet"

    def refresh_panel(self, app: "BattleshipApp") -> None:
        g = app.game
        p = app.boards_view.active_player
        b = g.boards[p]
        lines = ["  [dim]Your fleet:[/]"]
        fleet_by_kind = {s.kind: s for s in b.ships}
        for kind in FLEET_ORDER:
            ship = fleet_by_kind.get(kind)
            if ship is None:
                status = "[dim]— unplaced —[/]"
            elif ship.is_sunk:
                status = f"[bold rgb(240,90,70)]SUNK[/]  {len(ship.hits)}/{ship.length}"
            else:
                dots = "✸" * len(ship.hits) + "■" * (ship.length - len(ship.hits))
                status = f"[rgb(180,195,210)]{dots}[/]"
            badge = f"[bold rgb(200,170,110)]{kind.label[0]}[/]"
            lines.append(f"  {badge} {kind.label:<10} {status}")
        # Show opponent ships-remaining count when in battle/over.
        if g.phase in (Phase.BATTLE, Phase.OVER):
            opp = g.boards[1 - p]
            lines += [
                "",
                f"  [dim]Enemy fleet: {opp.ships_remaining}/5 afloat[/]",
            ]
        self.update("\n".join(lines))


class ControlsPanel(Static):
    def __init__(self) -> None:
        super().__init__("", id="controls")
        self.border_title = "Controls"

    def refresh_panel(self, app: "BattleshipApp") -> None:
        phase = app.game.phase
        if phase is Phase.PLACEMENT:
            lines = [
                "  [bold]Arrows[/]  move cursor",
                "  [bold]r[/]       rotate H/V",
                "  [bold]Space[/]   place ship",
                "  [bold]R[/]       random fleet",
                "  [bold]u[/]       undo last",
                "  [bold]Tab[/]     finish placing",
                "",
                "  [bold]?[/]       help",
                "  [bold]l[/]       legend",
                "  [bold]q[/]       quit",
            ]
        elif phase is Phase.BATTLE:
            lines = [
                "  [bold]Arrows[/]  move cursor",
                "  [bold]Space[/]   fire!",
                "  [bold]Enter[/]   fire!",
                "",
                "  [bold]?[/]       help",
                "  [bold]l[/]       legend",
                "  [bold]n[/]       new game",
                "  [bold]q[/]       quit",
                "",
                "  [dim]mouse: click target[/]",
            ]
        else:  # OVER
            lines = [
                "  [bold]n[/]       new game",
                "  [bold]q[/]       quit",
                "  [bold]?[/]       help",
                "  [bold]l[/]       legend",
            ]
        self.update("\n".join(lines))


# -------- the App --------

class BattleshipApp(App):
    CSS_PATH = "tui.tcss"
    TITLE = "Battleship TUI"

    BINDINGS = [
        Binding("q", "quit", "quit", show=True),
        Binding("ctrl+c", "quit", show=False),
        Binding("up",    "move_cursor(0,-1)", priority=True, show=False),
        Binding("down",  "move_cursor(0,1)",  priority=True, show=False),
        Binding("left",  "move_cursor(-1,0)", priority=True, show=False),
        Binding("right", "move_cursor(1,0)",  priority=True, show=False),
        Binding("space", "primary", show=True),
        Binding("enter", "primary", show=False),
        Binding("r",     "rotate", show=True),
        Binding("shift+r", "random_fleet", show=False),
        Binding("u",     "undo_place", show=True),
        Binding("tab",   "finish_placement", priority=True, show=True),
        Binding("b",     "finish_placement", show=True),
        Binding("n",     "new_game", show=True),
        Binding("question_mark,slash", "help", show=False),
        Binding("l",     "legend", show=False),
    ]

    def __init__(self, mode: str = "vs_ai", ai: str = "heatmap",
                 salvo: bool = False, seed: int | None = None,
                 sound: bool = False,
                 agent: bool = False, host: str = "127.0.0.1",
                 port: int = 8765) -> None:
        super().__init__()
        self._initial_mode = mode
        self._initial_ai = ai
        self._initial_salvo = salvo
        self._seed = seed
        self.game: Game = new_game(mode=mode, ai=ai, salvo=salvo, seed=seed)
        # vs_ai: AI is player 1, gets a random fleet immediately.
        if mode == "vs_ai":
            self.game.random_fleet(1)
        self.sounds = SoundBoard(enabled=sound)

        # Agent API state.
        self._agent_enabled = agent
        self._agent_host = host
        self._agent_port = port
        self._agent_api = None
        self._agent_runner = None

        # Widget refs — constructed up-front so type system sees them.
        self.boards_view: BoardsView = BoardsView(self.game)
        self.status_panel: StatusPanel = StatusPanel()
        self.fleet_panel: FleetPanel = FleetPanel()
        self.controls_panel: ControlsPanel = ControlsPanel()
        self.log_view: RichLog = RichLog(id="log", markup=True, max_lines=500)
        self.flash_bar: Static = Static(
            "Welcome to Battleship. Place your fleet to begin.  ?=help",
            id="flash-bar",
        )
        # Salvo queued shots (list of (x, y)) for the current volley.
        self._salvo_queue: list[tuple[int, int]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield self.flash_bar
        self.log_view.border_title = "Log"
        yield Horizontal(
            Vertical(
                self.boards_view,
                self.log_view,
                id="board-col",
            ),
            Vertical(
                self.status_panel,
                self.fleet_panel,
                self.controls_panel,
                id="side",
            ),
            id="body",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.boards_view.border_title = "Battlespace"
        self.status_panel.refresh_panel(self)
        self.fleet_panel.refresh_panel(self)
        self.controls_panel.refresh_panel(self)
        self.log_msg(f"[bold rgb(240,200,120)]New game:[/] {self.game.mode} "
                     f"{'salvo' if self.game.salvo else 'classic'}")
        self.set_focus(None)
        if self._agent_enabled:
            self.run_worker(self._start_agent_api(), exclusive=True)

    async def _start_agent_api(self) -> None:
        from .agent_api import AgentAPI, start_server

        def _on_change() -> None:
            self.boards_view.refresh()
            self.status_panel.refresh_panel(self)
            self.fleet_panel.refresh_panel(self)

        self._agent_api = AgentAPI(self.game, on_change=_on_change)
        try:
            runner, bound = await start_server(
                self._agent_api, host=self._agent_host, port=self._agent_port,
            )
        except OSError as e:
            self.log_msg(f"[red]agent API failed to bind[/] {e}")
            return
        self._agent_runner = runner
        self.log_msg(
            f"[bold rgb(80,220,110)]agent API listening[/] "
            f"http://{self._agent_host}:{bound}"
        )

    def log_msg(self, msg: str) -> None:
        self.log_view.write(msg)

    def flash(self, msg: str) -> None:
        self.flash_bar.update(msg)

    # --- actions ---

    def action_move_cursor(self, dx: int, dy: int) -> None:
        bv = self.boards_view
        nx = max(0, min(bv.cursor_x + dx, BOARD_W - 1))
        ny = max(0, min(bv.cursor_y + dy, BOARD_H - 1))
        bv.cursor_x = nx
        bv.cursor_y = ny

    def action_rotate(self) -> None:
        if self.game.phase is not Phase.PLACEMENT:
            return
        self.boards_view.placement_horizontal = not self.boards_view.placement_horizontal

    def action_random_fleet(self) -> None:
        if self.game.phase is not Phase.PLACEMENT:
            return
        p = self.boards_view.active_player
        self.game.random_fleet(p)
        self.sounds.play("place")
        self.flash("Random fleet placed. Tab to start battle.")
        self._refresh_all()

    def action_undo_place(self) -> None:
        if self.game.phase is not Phase.PLACEMENT:
            return
        p = self.boards_view.active_player
        if self.game.unplace_last(p):
            self.sounds.play("unplace")
            self.flash("Undid last placement.")
        self._refresh_all()

    def action_finish_placement(self) -> None:
        """Active player is done placing. In vs_ai we flip to BATTLE
        immediately. In hotseat we hand off to the other player, then
        enter BATTLE when both are placed."""
        g = self.game
        if g.phase is not Phase.PLACEMENT:
            return
        p = self.boards_view.active_player
        if not g.boards[p].all_placed:
            self.flash("[yellow]Place all 5 ships first (or press R for random).[/]")
            return
        if g.mode == "vs_ai":
            if g.start_battle():
                self.flash("Enemy fleet deployed. Opening salvo — fire!")
                self.log_msg("[bold rgb(80,220,110)]Battle begins.[/]")
                self.boards_view.cursor_board = 1
                self.boards_view.cursor_x = 0
                self.boards_view.cursor_y = 0
                self._refresh_all()
            return
        # Hotseat: if opponent hasn't placed yet, hand off via the PassBoard modal.
        other = 1 - p
        if g.boards[other].all_placed:
            if g.start_battle():
                # Pass-board to Player 1 for the first volley.
                self.boards_view.set_active_player(0)
                self.boards_view.cursor_board = 1
                self.boards_view.cursor_x = 0
                self.boards_view.cursor_y = 0
                self._refresh_all()
                self.push_screen(PassBoardScreen(next_player=0,
                                                 label="BATTLE BEGINS"))
            return
        # Hand off to the other player for their placement phase.
        def _after_pass() -> None:
            self.boards_view.set_active_player(other)
            self.boards_view.cursor_x = 0
            self.boards_view.cursor_y = 0
            self.boards_view.placement_horizontal = True
            self._refresh_all()
        self.push_screen(PassBoardScreen(next_player=other,
                                          label="PASS THE KEYBOARD",
                                          on_done=_after_pass))

    def action_primary(self) -> None:
        """Space/Enter — place (in PLACEMENT) or fire (in BATTLE)."""
        g = self.game
        if g.phase is Phase.PLACEMENT:
            self._try_place()
        elif g.phase is Phase.BATTLE:
            self._try_fire()

    def action_new_game(self) -> None:
        self.game = new_game(mode=self._initial_mode, ai=self._initial_ai,
                             salvo=self._initial_salvo, seed=None)
        if self._initial_mode == "vs_ai":
            self.game.random_fleet(1)
        self.boards_view.attach_game(self.game, active_player=0)
        self.boards_view.cursor_board = 0
        self.boards_view.placement_horizontal = True
        self._salvo_queue.clear()
        if self._agent_api is not None:
            self._agent_api.set_game(self.game)
        self.flash("New game. Place your fleet.")
        self.log_msg(f"[bold rgb(240,200,120)]New game:[/] {self.game.mode} "
                     f"{'salvo' if self.game.salvo else 'classic'}")
        self._refresh_all()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_legend(self) -> None:
        self.push_screen(LegendScreen())

    # --- internals ---

    def _try_place(self) -> None:
        g = self.game
        p = self.boards_view.active_player
        idx = g.next_to_place[p]
        if idx >= len(FLEET_ORDER):
            self.flash("[yellow]All ships placed. Tab to finish.[/]")
            return
        kind = FLEET_ORDER[idx]
        r = g.place_ship(p, kind, self.boards_view.cursor_x,
                         self.boards_view.cursor_y,
                         self.boards_view.placement_horizontal)
        if r is PlaceResult.OK:
            self.sounds.play("place")
            self.flash(f"Placed [bold]{kind.label}[/].")
            if g.boards[p].all_placed:
                self.flash("[bold rgb(80,220,110)]Fleet complete![/] Tab to begin battle.")
        elif r is PlaceResult.OUT_OF_BOUNDS:
            self.sounds.play("invalid")
            self.flash("[yellow]Out of bounds — rotate or move.[/]")
        elif r is PlaceResult.OVERLAP:
            self.sounds.play("invalid")
            self.flash("[yellow]Overlaps another ship.[/]")
        elif r is PlaceResult.ALREADY_PLACED:
            self.flash("[yellow]Already placed this ship.[/]")
        self._refresh_all()

    def _try_fire(self) -> None:
        g = self.game
        if g.turn != 0 and g.mode == "vs_ai":
            self.flash("[yellow]Enemy's turn — wait.[/]")
            return
        if self.boards_view.cursor_board != 1:
            # Move cursor to tracking board first.
            self.boards_view.cursor_board = 1
            self.flash("[dim]Cursor moved to targeting board.[/]")
            self._refresh_all()
            return
        tx, ty = self.boards_view.cursor_x, self.boards_view.cursor_y
        shooter = g.turn
        # Salvo mode: queue up to ships_remaining shots, then resolve.
        if g.salvo:
            # Check already queued or already fired.
            b = g.boards[shooter]
            if b.tracking_cells[b.idx(tx, ty)] != UNKNOWN:
                self.flash("[yellow]Already fired at that cell.[/]")
                self.sounds.play("invalid")
                return
            if (tx, ty) in self._salvo_queue:
                self.flash("[yellow]Already queued for this volley.[/]")
                return
            self._salvo_queue.append((tx, ty))
            shots_needed = g.salvo_shots_this_turn(shooter)
            if len(self._salvo_queue) < shots_needed:
                self.flash(f"Queued volley {len(self._salvo_queue)}/{shots_needed}")
                return
            # Volley full — fire all.
            self._resolve_salvo(shooter)
        else:
            r = g.fire(shooter, tx, ty)
            self._announce_shot(shooter, tx, ty, r)
        self._refresh_all()
        # Check for AI turn.
        if g.phase is Phase.BATTLE and g.mode == "vs_ai" and g.turn == 1:
            self._run_ai_turn()

    def _resolve_salvo(self, shooter: int) -> None:
        g = self.game
        results: list[tuple[int, int, ShotResult]] = []
        for (sx, sy) in list(self._salvo_queue):
            r = g.fire(shooter, sx, sy)
            results.append((sx, sy, r))
            if r is ShotResult.WIN:
                break
        self._salvo_queue.clear()
        g.end_volley()
        for (sx, sy, r) in results:
            self._announce_shot(shooter, sx, sy, r)

    def _announce_shot(self, shooter: int, x: int, y: int, r: ShotResult) -> None:
        side = "P1" if shooter == 0 else ("P2" if self.game.mode == "hotseat" else "AI")
        coord = f"{chr(ord('A') + x)}{y + 1}"
        if r is ShotResult.MISS:
            self.sounds.play("miss")
            self.flash(f"{side} at {coord} — [rgb(100,150,200)]MISS[/]")
            self.log_msg(f"[rgb(100,150,200)]{side} {coord}: miss[/]")
        elif r is ShotResult.HIT:
            self.sounds.play("hit")
            self.flash(f"{side} at {coord} — [bold rgb(240,90,70)]HIT![/]")
            self.log_msg(f"[bold rgb(240,90,70)]{side} {coord}: HIT[/]")
        elif r is ShotResult.SUNK:
            self.sounds.play("sunk")
            self.flash(f"{side} at {coord} — [bold rgb(245,190,80)]SUNK![/]")
            self.log_msg(f"[bold rgb(245,190,80)]{side} {coord}: SUNK a ship[/]")
        elif r is ShotResult.WIN:
            self.sounds.play("win")
            self.flash(f"{side} at {coord} — [bold rgb(245,190,80)]VICTORY![/]")
            self.log_msg(f"[bold rgb(245,190,80)]★ {side} wins the match ★[/]")
            self._on_game_over(shooter)
        elif r is ShotResult.INVALID:
            self.sounds.play("invalid")
            self.flash("[yellow]Invalid shot.[/]")

    def _run_ai_turn(self) -> None:
        """AI plays, including potential follow-up if salvo."""
        if self.game.phase is not Phase.BATTLE:
            return
        if self.game.mode != "vs_ai":
            return
        if self.game.turn != 1:
            return
        # For immediate feedback in QA/tests, play synchronously.
        # In interactive use we could stagger with set_timer but keep simple.
        results = self.game.ai_take_turn()
        # Announce each AI shot from the log (last N entries).
        recent = self.game.shot_log[-len(results):] if results else []
        for entry in recent:
            if entry["player"] == 1:
                result = ShotResult(entry["result"])
                self._announce_shot(1, entry["x"], entry["y"], result)
        self._refresh_all()

    def _on_game_over(self, winner_player: int) -> None:
        self.push_screen(ResultScreen(
            won=(winner_player == 0 and self.game.mode == "vs_ai") or
                (self.game.mode == "hotseat"),
            winner_label=(f"Player {winner_player + 1}"
                          if self.game.mode == "hotseat"
                          else ("You" if winner_player == 0 else "The AI")),
            shots=len(self.game.shot_log),
            on_new=lambda: self.action_new_game(),
        ))

    def _refresh_all(self) -> None:
        self.boards_view.refresh()
        self.status_panel.refresh_panel(self)
        self.fleet_panel.refresh_panel(self)
        self.controls_panel.refresh_panel(self)

    def on_boards_view_cell_action(self, msg: BoardsView.CellAction) -> None:
        if msg.action == "place":
            self._try_place()
        elif msg.action == "fire":
            self._try_fire()


# -------- entry --------

def run(mode: str = "vs_ai", *, ai: str = "heatmap",
        salvo: bool = False, seed: int | None = None,
        sound: bool = False,
        agent: bool = False, host: str = "127.0.0.1",
        port: int = 8765) -> None:
    app = BattleshipApp(mode=mode, ai=ai, salvo=salvo, seed=seed,
                         sound=sound, agent=agent, host=host, port=port)
    try:
        app.run()
    finally:
        import sys
        sys.stdout.write(
            "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l\033[?25h"
        )
        sys.stdout.flush()
        app.sounds.close()
