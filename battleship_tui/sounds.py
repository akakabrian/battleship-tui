"""Opt-in synth sound effects for Battleship.

Same design contract as minesweeper-tui's sounds.py: silent-on-failure,
debounced per-name, stdlib synth only.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path


# (freqs Hz, duration s, attack ms, decay ms)
_SOUND_SPECS: dict[str, tuple[list[int], float, int, int]] = {
    "place":     ([660, 880],          0.07, 3, 30),   # click-in
    "unplace":   ([440, 330],          0.06, 3, 25),   # click-out
    "fire":      ([1200, 800, 400],    0.15, 5, 80),   # zipping shell
    "miss":      ([180, 140],          0.25, 5, 150),  # dull splash
    "hit":       ([220, 180, 110],     0.30, 4, 200),  # crump
    "sunk":      ([90, 70, 50, 30],    0.60, 5, 450),  # big boom
    "win":       ([660, 880, 1100, 1320], 0.55, 30, 300),  # victory fanfare
    "invalid":   ([200, 150],          0.12, 2, 50),   # low buzz
}


def _synth(freqs: list[int], duration: float, attack_ms: int,
           decay_ms: int, sample_rate: int = 22_050) -> bytes:
    n = int(sample_rate * duration)
    attack = int(sample_rate * attack_ms / 1000)
    decay = int(sample_rate * decay_ms / 1000)
    attack = min(attack, n // 2)
    decay = min(decay, n - attack)
    frames = bytearray()
    for i in range(n):
        if i < attack:
            env = i / max(attack, 1)
        elif i > n - decay:
            env = max(0.0, (n - i) / max(decay, 1))
        else:
            env = 1.0
        t = i / sample_rate
        sample = 0.0
        for f in freqs:
            sample += math.sin(2 * math.pi * f * t)
        sample = (sample / len(freqs)) * env * 0.3
        frames.extend(struct.pack("<h", int(sample * 32767)))
    return bytes(frames)


def _detect_player() -> list[str] | None:
    for cmd in (["paplay"], ["aplay", "-q"], ["afplay"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


class SoundBoard:
    """Lazily-synthesised tones played via background subprocess."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._player = _detect_player() if enabled else None
        self._paths: dict[str, Path] = {}
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self._failed = False
        self._last_played: dict[str, float] = {}
        self._min_gap_s: float = 0.08
        if self.enabled and self._player is None:
            self._failed = True
            self.enabled = False

    def _ensure(self, name: str) -> Path | None:
        if not self.enabled or self._failed:
            return None
        if name in self._paths:
            return self._paths[name]
        if name not in _SOUND_SPECS:
            return None
        if self._tmpdir is None:
            self._tmpdir = tempfile.TemporaryDirectory(prefix="bship-sfx-")
        freqs, dur, atk, dcy = _SOUND_SPECS[name]
        data = _synth(freqs, dur, atk, dcy)
        path = Path(self._tmpdir.name) / f"{name}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22_050)
            w.writeframes(data)
        self._paths[name] = path
        return path

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last_played.get(name, 0.0) < self._min_gap_s:
            return
        self._last_played[name] = now
        path = self._ensure(name)
        if path is None or self._player is None:
            return
        try:
            subprocess.Popen(
                [*self._player, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, FileNotFoundError):
            self.enabled = False
            self._failed = True

    def close(self) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None
