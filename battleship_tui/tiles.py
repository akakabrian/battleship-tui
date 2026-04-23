"""Visual tables for Battleship cells.

Pre-parse `rich.style.Style` objects at import time so `render_line` doesn't
re-parse per cell.

Palette: dark navy background with amber/salmon accents — reads as a
tactical console. Shot outcomes are the loudest colors (bright red hit,
blue-grey miss, gold sunk outline).
"""

from __future__ import annotations

from rich.style import Style


# -------- glyphs --------

# Own-board (your fleet + incoming fire)
GLYPH_WATER = "·"      # empty water, no shot
GLYPH_MISS_OWN = "○"   # opponent shot here and missed
GLYPH_SHIP = "■"       # your ship, unhit
GLYPH_HIT_OWN = "✸"    # your ship, hit

# Tracking board (your shots at opponent)
GLYPH_UNKNOWN = "·"    # not shot yet
GLYPH_MISS_TRACK = "○" # you missed here
GLYPH_HIT_TRACK = "✸"  # you hit here
GLYPH_SUNK_OUTLINE = "▣"  # cell is part of a known-sunk enemy ship

# Cursor
GLYPH_CURSOR = None    # the cell keeps its glyph but gets cursor bg

# Placement preview (ghost ship under cursor)
GLYPH_GHOST_OK = "□"   # valid placement preview
GLYPH_GHOST_BAD = "▨"  # invalid placement preview

# Ship-kind badges — for the fleet roster panel + placement selector.
SHIP_BADGES: dict[str, str] = {
    "CARRIER":    "C",
    "BATTLESHIP": "B",
    "CRUISER":    "R",
    "SUBMARINE":  "S",
    "DESTROYER":  "D",
}


# -------- colors --------

# Water / unknown — muted navy.
WATER_BG = ("#0a1420", "#0c1624")   # two-tone checkerboard
WATER_FG = "#3a4b5e"

# Own ship cell — cool steel.
SHIP_FG = "rgb(180,195,210)"
SHIP_BG = ("#18232e", "#1a2530")

# Cursor highlight — warm amber, readable through any state.
CURSOR_BG = "#3a2e12"
CURSOR_FG = "rgb(255,220,120)"

# Miss — blue dot on dark water.
MISS_FG = "rgb(100,150,200)"
MISS_BG = "#0a1420"

# Hit — red X on ember.
HIT_FG = "rgb(240,90,70)"
HIT_BG = "rgb(80,14,14)"

# Sunk outline — gold.
SUNK_FG = "rgb(245,190,80)"
SUNK_BG = "#241a06"

# Ghost (placement preview)
GHOST_OK_FG = "rgb(80,220,140)"
GHOST_OK_BG = "#0c2014"
GHOST_BAD_FG = "rgb(240,90,70)"
GHOST_BAD_BG = "#2a0a0a"

# Active-board frame highlight (the board the cursor is on)
ACTIVE_FRAME = "rgb(240,200,120)"
INACTIVE_FRAME = "#3a3a42"


# -------- pre-parsed style cache --------

_STYLE_CACHE: dict[tuple, Style] = {}


def _style(fg: str | None, bg: str, bold: bool = False) -> Style:
    key = (fg, bg, bold)
    s = _STYLE_CACHE.get(key)
    if s is None:
        s = Style(color=fg, bgcolor=bg, bold=bold)
        _STYLE_CACHE[key] = s
    return s


def water_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else WATER_BG[(x + y) & 1]
    return _style(WATER_FG, bg)


def ship_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else SHIP_BG[(x + y) & 1]
    return _style(SHIP_FG, bg, bold=True)


def miss_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else MISS_BG
    return _style(MISS_FG, bg, bold=True)


def hit_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else HIT_BG
    return _style(HIT_FG, bg, bold=True)


def sunk_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else SUNK_BG
    return _style(SUNK_FG, bg, bold=True)


def ghost_style(x: int, y: int, valid: bool, cursor: bool = False) -> Style:
    if valid:
        fg, bg = GHOST_OK_FG, GHOST_OK_BG
    else:
        fg, bg = GHOST_BAD_FG, GHOST_BAD_BG
    if cursor:
        bg = CURSOR_BG
    return _style(fg, bg, bold=True)


def label_style() -> Style:
    return _style("rgb(200,170,110)", "#0a0a0c", bold=True)


def frame_active_style() -> Style:
    return _style(ACTIVE_FRAME, "#0a0a0c", bold=True)


def frame_inactive_style() -> Style:
    return _style(INACTIVE_FRAME, "#0a0a0c")
