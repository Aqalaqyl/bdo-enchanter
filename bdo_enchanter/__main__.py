"""Command line entry point: ./enchanter <command>."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import Config, Stage
from .phases import Controls, GameError, Halt, run_phase

log = logging.getLogger("enchanter")


def cmd_check(cfg: Config) -> int:
    from .game import RealGame
    from .screen import Screen

    screen = Screen(cfg)
    try:
        game = RealGame(cfg, screen, interactive=False)
    except GameError as exc:
        print(exc)
        return 1
    ok = True
    print(f"game window: {'found' if screen.game_window_id() else 'not found (countdown mode)'}")
    print(f"enhancement window open: {game.enhancement_open()}")
    try:
        print(f"failstack: {game.read_failstack()}")
    except GameError as exc:
        print(f"failstack: {exc}")
        ok = False
    for name, steps in cfg["flows"].items():
        print(f"flow {name}: {len(steps)} step(s)")
        for s in steps:
            if "click" in s:
                m = screen.find(s["click"])
                print(f"    {s['click']}: {'found' if m else 'not on screen'}{' (optional)' if s.get('optional') else ''}")
    for item in cfg["items"]:
        counts = game.count_items(item)
        print(f"{item['name']}: " + ", ".join(f"{s.name}={counts[s]}" for s in Stage)
              + f"   (PRI goal {item.get('pri_count', 1)})")
    print("OK" if ok else "problems found; run ./enchanter setup")
    return 0 if ok else 1


def cmd_phase(cfg: Config, stage: Stage, args) -> int:
    from .game import RealGame
    from .screen import Screen

    items = cfg["items"]
    if not items:
        log.error("no accessories configured; run ./enchanter setup")
        return 1
    if args.count is not None:
        for item in items:
            item["pri_count"] = args.count

    controls = Controls()
    controls.install_hotkeys(cfg["hotkeys"])
    try:
        game = RealGame(cfg, Screen(cfg), check=controls.check)
    except GameError as exc:
        log.error("%s", exc)
        return 2

    log.info("%s phase: %s", stage.name, "; ".join(
        f"{i['name']} -> {i.get('pri_count', 1)} PRI" if stage == Stage.PRI else f"all PRI {i['name']} -> DUO"
        for i in items))
    log.info("starting in %d s (F9 stop, F10 pause)", args.countdown)
    time.sleep(args.countdown)

    code = 0
    try:
        stats = run_phase(game, items, stage, cfg, controls, max_attempts=args.attempts)
    except KeyboardInterrupt:
        log.info("stopped by user")
        return 130
    except Halt as exc:
        log.warning("paused for you: %s", exc)
        return 3
    except GameError as exc:
        log.error("%s", exc)
        return 2
    log.info(stats.summary())
    for note in stats.notes:
        log.info("  %s", note)
    if stage == Stage.PRI:
        log.info("when you are ready for DUO, run: ./enchanter duo")
    return code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="enchanter", description="BDO accessory auto-enhancer (Linux/X11)")
    p.add_argument("--config", default="config.yaml", type=Path)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="guided setup: record menus, capture pictures")
    sub.add_parser("check", help="read the screen and report what I see; clicks nothing")
    for name, help_ in (("pri", "enhance BASE copies to PRI until each type reaches its PRI goal"),
                        ("duo", "enhance every PRI copy to DUO")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--attempts", type=int, help="stop after this many attempts")
        sp.add_argument("--count", type=int, help="override the PRI goal for every accessory type")
        sp.add_argument("--countdown", type=int, default=3)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    if args.command == "setup":
        from .wizard import run_wizard

        return run_wizard(args.config)
    cfg = Config.load(args.config)
    if args.command == "check":
        return cmd_check(cfg)
    return cmd_phase(cfg, Stage.PRI if args.command == "pri" else Stage.DUO, args)


if __name__ == "__main__":
    sys.exit(main())
