"""Phase logic: what to attempt next and when to stop.

Everything here talks to the game through a small interface so it can be
tested with a fake game (see tests/).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from .config import Stage

log = logging.getLogger("enchanter")


class GameError(RuntimeError):
    """Something on screen did not match expectations; stop and tell the user."""


class Halt(RuntimeError):
    """Nothing is wrong, but a human has to decide (e.g. an oversized failstack)."""


class Game(Protocol):
    def ensure_enhancement_open(self) -> None: ...
    def read_failstack(self) -> int: ...
    def raise_failstack_to(self, target: int) -> int: ...
    def count_items(self, item: dict) -> dict[Stage, int]: ...
    def place_item(self, item: dict, stage: Stage) -> bool: ...
    def enhance_and_wait(self, fs_before: int, stage: Stage) -> bool | None: ...
    def ensure_template(self, item: dict, stage: Stage) -> None: ...


class Controls:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.paused = threading.Event()

    def install_hotkeys(self, hotkeys: dict) -> None:
        try:
            from pynput import keyboard
        except ImportError:
            log.warning("pynput missing; hotkeys disabled (Ctrl+C still works)")
            return

        def spec(name: str) -> str:
            name = name.strip().lower()
            return name if name.startswith("<") or len(name) == 1 else f"<{name}>"

        listener = keyboard.GlobalHotKeys({
            spec(hotkeys["stop"]): self.stop.set,
            spec(hotkeys["pause"]): self._toggle,
        })
        listener.daemon = True
        listener.start()
        log.info("hotkeys: %s = stop, %s = pause/resume", hotkeys["stop"], hotkeys["pause"])

    def _toggle(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            log.info("resumed")
        else:
            self.paused.set()
            log.info("paused")

    def check(self) -> None:
        while self.paused.is_set() and not self.stop.is_set():
            time.sleep(0.2)
        if self.stop.is_set():
            raise KeyboardInterrupt


@dataclass
class Stats:
    attempts: int = 0
    success: int = 0
    fail: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"attempts={self.attempts} success={self.success} fail={self.fail}"


# --------------------------------------------------------------------------- #
def prepare_failstack(game: Game, target: int, max_overshoot: int) -> int:
    fs = game.read_failstack()
    if fs >= target:
        if fs - target > max_overshoot:
            raise Halt(
                f"current failstack {fs} is more than {max_overshoot} above the {target} "
                "this attempt needs; use or store that stack manually, then run again"
            )
        return fs
    log.info("  raising failstack %d -> %d with Black Stones", fs, target)
    fs = game.raise_failstack_to(target)
    if fs < target:
        raise GameError(f"failstack is {fs} after consuming stones, expected {target}")
    return fs


def attempt(game: Game, item: dict, stage: Stage, cfg, controls: Controls, stats: Stats) -> bool:
    """One enhancement attempt taking ``item`` from ``stage - 1`` to ``stage``."""
    source = Stage(stage - 1)
    target_fs = cfg.target_fs(stage)
    log.info("attempt %d: %s %s -> %s at %d FS", stats.attempts + 1, item["name"], source.name, stage.name, target_fs)

    game.ensure_enhancement_open()
    fs = prepare_failstack(game, target_fs, cfg["failstack"]["max_overshoot"])
    controls.check()
    game.ensure_enhancement_open()
    if not game.place_item(item, source):
        raise GameError(f"no {source.name} {item['name']} found in the inventory area")
    result = game.enhance_and_wait(fs, stage)
    stats.attempts += 1
    if result is None:
        raise GameError(
            "failstack did not change after Enhance: no material in the inventory, "
            "the wrong item was placed, or the Enhance picture no longer matches"
        )
    if result:
        stats.success += 1
        log.info("  SUCCESS: %s is now %s", item["name"], stage.name)
        game.ensure_template(item, stage)
    else:
        stats.fail += 1
        log.info("  FAIL: %s destroyed (failstack now %d)", item["name"], game.read_failstack())
    return result


def run_phase(game: Game, items: list[dict], stage: Stage, cfg, controls: Controls,
              max_attempts: int | None = None) -> Stats:
    """PRI phase: reach ``pri_count`` PRI copies per item. DUO phase: no PRI copies left."""
    stats = Stats()
    for item in items:
        want_pri = int(item.get("pri_count", 1))
        while max_attempts is None or stats.attempts < max_attempts:
            controls.check()
            game.ensure_enhancement_open()
            counts = game.count_items(item)
            log.info("%s in inventory: %s", item["name"],
                     ", ".join(f"{s.name}={counts.get(s, 0)}" for s in Stage))

            if stage == Stage.PRI:
                if counts.get(Stage.PRI, 0) >= want_pri:
                    stats.notes.append(f"{item['name']}: {want_pri} PRI reached")
                    break
                if counts.get(Stage.BASE, 0) < 2:
                    stats.notes.append(f"{item['name']}: need 2 BASE copies (item + material), "
                                       f"found {counts.get(Stage.BASE, 0)}")
                    break
            else:
                if counts.get(Stage.PRI, 0) == 0:
                    stats.notes.append(f"{item['name']}: no PRI copies left")
                    break
                if counts.get(Stage.BASE, 0) < 1:
                    stats.notes.append(f"{item['name']}: need a BASE copy as material, found 0")
                    break

            attempt(game, item, stage, cfg, controls, stats)
        else:
            stats.notes.append(f"stopped after {max_attempts} attempt(s) as requested")
            break
    return stats
