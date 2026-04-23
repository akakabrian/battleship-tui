"""Entry point — `python battleship.py [--mode vs_ai|hotseat] [--ai ...]`.

  python battleship.py                          # vs AI, heatmap difficulty, classic
  python battleship.py --mode hotseat           # 2 humans, pass-and-play
  python battleship.py --ai random              # random AI (easy)
  python battleship.py --ai optimal             # hardest AI
  python battleship.py --salvo                  # salvo mode variant
  python battleship.py --seed 42                # deterministic RNG
  python battleship.py --sound                  # synth SFX
  python battleship.py --agent                  # TUI + REST API on :8765
  python battleship.py --headless               # server only, no TUI
"""

from __future__ import annotations

import argparse

from battleship_tui.app import run


def main() -> None:
    p = argparse.ArgumentParser(prog="battleship-tui")
    p.add_argument("--mode", default="vs_ai",
                   choices=["vs_ai", "hotseat"],
                   help="vs_ai (default) or hotseat (2-human pass-and-play)")
    p.add_argument("--ai", default="heatmap",
                   choices=["random", "heatmap", "optimal"],
                   help="AI difficulty (vs_ai only)")
    p.add_argument("--salvo", action="store_true",
                   help="salvo mode — fire N shots per turn where N=ships remaining")
    p.add_argument("--seed", type=int, help="RNG seed for reproducible games")
    p.add_argument("--sound", action="store_true",
                   help="enable synth SFX (default off)")
    p.add_argument("--agent", action="store_true",
                   help="expose the REST agent API alongside the TUI")
    p.add_argument("--headless", action="store_true",
                   help="run the agent API only, no TUI")
    p.add_argument("--host", default="127.0.0.1",
                   help="agent API host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765,
                   help="agent API port (default 8765, 0=auto)")
    args = p.parse_args()
    if args.headless:
        import asyncio
        from battleship_tui.agent_api import run_headless
        asyncio.run(run_headless(
            mode=args.mode, ai=args.ai, salvo=args.salvo, seed=args.seed,
            host=args.host, port=args.port,
        ))
        return
    run(mode=args.mode, ai=args.ai, salvo=args.salvo, seed=args.seed,
        sound=args.sound, agent=args.agent, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
