"""Modal screens for Battleship TUI: Help, NewGame, PassBoard, Result, Legend."""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


HELP_TEXT = """
[bold rgb(240,200,120)]BATTLESHIP — TUI[/]

[bold]Placement[/]
  Arrow keys          move cursor on YOUR FLEET board
  r                   rotate ship horizontal / vertical
  Space / Enter       place the current ship
  R (Shift+r)         auto-place full random fleet
  u                   undo last placement
  Tab                 finish placement (both fleets must be placed)

[bold]Battle[/]
  Arrow keys          aim on TARGETING board
  Space / Enter       fire!
  Mouse click         also works (left-click to place/fire)

[bold]Menus[/]
  ?                   this help
  l                   legend (symbol key)
  n                   new game
  q                   quit

[bold]Fleet (5 ships, 17 cells total)[/]
  Carrier     5
  Battleship  4
  Cruiser     3
  Submarine   3
  Destroyer   2

[bold]Rules[/]
  Place your fleet. Take turns firing shots at the opponent's grid.
  A hit on every cell of a ship sinks it. Sink the whole enemy fleet
  to win. In salvo mode, you fire as many shots per volley as you
  have ships remaining.
"""


LEGEND_TEXT = """
[bold rgb(240,200,120)]LEGEND[/]

[bold]Your fleet (left board)[/]
  [rgb(180,195,210)]■[/]    ship cell (unhit)
  [bold rgb(240,90,70)]✸[/]   ship cell, hit
  [rgb(100,150,200)]○[/]   opponent missed here
  [dim]·[/]    water

[bold]Targeting (right board)[/]
  [dim]·[/]    unknown — not fired yet
  [rgb(100,150,200)]○[/]   your miss
  [bold rgb(240,90,70)]✸[/]   your hit
  [bold rgb(245,190,80)]▣[/]   part of a [bold]sunk[/] enemy ship

[bold]Placement preview[/]
  [bold rgb(80,220,140)]□[/]   valid placement under cursor
  [bold rgb(240,90,70)]▨[/]   invalid (off board or overlap)
"""


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,question_mark", "app.pop_screen", "close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(HELP_TEXT, id="help-body"),
            id="help-container",
        )


class LegendScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,l", "app.pop_screen", "close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(LEGEND_TEXT, id="legend-body"),
            id="legend-container",
        )


class PassBoardScreen(ModalScreen):
    """Hotseat pass-the-keyboard transition — hides the board until the next
    player confirms they're ready."""

    BINDINGS = [
        Binding("space,enter", "ready", show=False),
        Binding("escape", "app.pop_screen", show=False),
    ]

    def __init__(self, next_player: int, label: str = "PASS THE KEYBOARD",
                 on_done: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.next_player = next_player
        self.label = label
        self.on_done = on_done

    def compose(self) -> ComposeResult:
        lines = [
            f"[bold rgb(240,200,120)]{self.label}[/]",
            "",
            f"  [bold]Player {self.next_player + 1}[/] — look away until ready.",
            "",
            "  Press [bold]Space[/] or [bold]Enter[/] when the next player",
            "  is in the seat.",
        ]
        yield Vertical(
            Static("\n".join(lines), id="pass-body"),
            id="pass-container",
        )

    def action_ready(self) -> None:
        if self.on_done is not None:
            self.on_done()
        self.app.pop_screen()


class ResultScreen(ModalScreen):
    """Shown on game over. Press n for new game, q/escape to dismiss."""

    BINDINGS = [
        Binding("escape,q", "app.pop_screen", "close"),
        Binding("n", "new_game", show=False),
    ]

    def __init__(self, won: bool, winner_label: str, shots: int,
                 on_new: Callable[[], None]) -> None:
        super().__init__()
        self.won = won
        self.winner_label = winner_label
        self.shots = shots
        self.on_new = on_new

    def compose(self) -> ComposeResult:
        if self.won:
            title = f"[bold rgb(245,190,80)]★ {self.winner_label} WINS ★[/]"
            icon = "[bold rgb(245,190,80)]★[/]"
        else:
            title = f"[bold rgb(240,90,70)]Defeated[/] — {self.winner_label} wins"
            icon = "[bold rgb(240,90,70)]✸[/]"
        lines = [
            f"    {icon}  {title}  {icon}",
            "",
            f"  Total shots: [bold]{self.shots}[/]",
            "",
            "  [dim]n[/] — new game    [dim]Esc[/] — close (stay on board)",
        ]
        yield Vertical(
            Static("\n".join(lines), id="result-body"),
            id="result-container",
        )

    def action_new_game(self) -> None:
        self.app.pop_screen()
        self.on_new()


class NewGameScreen(ModalScreen):
    """Reserved for a future new-game config modal. The main App currently
    relies on CLI flags for mode/ai/salvo; this stub lives here to match the
    skill's layout and may be wired up in a polish pass."""

    BINDINGS = [Binding("escape", "app.pop_screen", "close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[dim]New-game config modal — not yet wired. "
                   "Restart with --mode / --ai / --salvo for now.[/]",
                   id="newgame-body"),
            id="newgame-container",
        )
