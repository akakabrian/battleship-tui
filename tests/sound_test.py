"""Sound diagnostic — 'I can't hear anything' triage script.

Prints:
  - detected player command
  - where synth WAV files land
  - plays one sound synchronously so any exit code is visible

Usage:
    make test-sound
    .venv/bin/python -m tests.sound_test
"""

from __future__ import annotations

import subprocess
import sys

from battleship_tui.sounds import SoundBoard, _SOUND_SPECS, _detect_player


def main() -> int:
    player = _detect_player()
    print(f"detected player: {player}")
    if player is None:
        print("  -> no paplay/aplay/afplay on PATH. Install pulseaudio-utils "
              "or alsa-utils.")
        return 1

    sb = SoundBoard(enabled=True)
    print(f"SoundBoard.enabled = {sb.enabled}")
    print(f"sounds available   = {sorted(_SOUND_SPECS.keys())}")
    # Synthesise + play one sound synchronously so the exit code is visible.
    name = "win"
    path = sb._ensure(name)
    print(f"synthed {name!r} → {path}")
    if path is None:
        print("  -> synth failed")
        return 2
    print(f"playing {name!r} synchronously (check your speakers)...")
    rc = subprocess.call([*player, str(path)])
    print(f"player exit code: {rc}")
    sb.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
