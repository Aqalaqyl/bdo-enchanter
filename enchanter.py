#!/usr/bin/env python3
"""Auto-enhancer for yellow (boss) accessories in Black Desert Online.

Builds failstacks with Black Stones to a per-stage target (PRI/DUO), puts the
accessory in the Black Spirit enhancement window and presses Enhance, then
reads the failstack counter to tell success from failure.

Usage:
    python enchanter.py run   [--config config.yaml]
    python enchanter.py check [--config config.yaml]   # verify OCR/templates
    python enchanter.py sim   [--config config.yaml]   # dry run, no input sent
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import threading
import time
from pathlib import Path

import yaml

from planner import (
    FAIL_GAIN,
    Done,
    Halt,
    Item,
    Plan,
    Stage,
    apply_result,
    choose_next,
    expand_items,
)

log = logging.getLogger("enchanter")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DEFAULTS = {
    "delays": {
        "after_click": 0.4,
        "after_failstack": 0.6,
        "after_enhance": 3.0,
        "result_timeout": 10.0,
    },
    "failstack": {
        "max_overshoot": 3,
        "verify_retries": 3,
    },
    "targets": {"PRI": 15, "DUO": 40},
    "match_threshold": 0.85,
    "hotkeys": {"stop": "f9", "pause": "f10"},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        cfg = deep_merge(DEFAULTS, yaml.safe_load(fh) or {})
    cfg["_dir"] = path.resolve().parent
    cfg["targets"] = {Stage.parse(k): int(v) for k, v in cfg["targets"].items()}
    for required in ("items",):
        if required not in cfg:
            raise SystemExit(f"config: missing required key '{required}'")
    return cfg


# --------------------------------------------------------------------------- #
# Control flags (hotkeys)
# --------------------------------------------------------------------------- #
class Controls:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.paused = threading.Event()

    def install(self, hotkeys: dict) -> None:
        try:
            import keyboard  # type: ignore
        except ImportError:
            log.warning("'keyboard' not installed; hotkeys disabled (Ctrl+C still works)")
            return
        keyboard.add_hotkey(hotkeys["stop"], self.stop.set)
        keyboard.add_hotkey(hotkeys["pause"], self._toggle_pause)
        log.info("hotkeys: %s = stop, %s = pause/resume", hotkeys["stop"], hotkeys["pause"])

    def _toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            log.info("resumed")
        else:
            self.paused.set()
            log.info("paused")

    def wait_if_paused(self) -> None:
        while self.paused.is_set() and not self.stop.is_set():
            time.sleep(0.2)

    def check(self) -> None:
        self.wait_if_paused()
        if self.stop.is_set():
            raise KeyboardInterrupt


# --------------------------------------------------------------------------- #
# Screen layer
# --------------------------------------------------------------------------- #
class Screen:
    """Thin wrapper over mss / OpenCV / pyautogui / tesseract."""

    def __init__(self, cfg: dict) -> None:
        import cv2  # noqa: F401
        import mss
        import numpy as np  # noqa: F401
        import pyautogui

        self.cfg = cfg
        self.sct = mss.mss()
        pyautogui.FAILSAFE = True  # slam mouse into a screen corner to abort
        pyautogui.PAUSE = 0.05
        self._template_cache: dict[str, object] = {}

        tess = cfg.get("tesseract_cmd")
        if tess:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = tess

    # -- capture ------------------------------------------------------------
    def grab(self, region: tuple[int, int, int, int] | None = None):
        import cv2
        import numpy as np

        if region:
            x, y, w, h = region
            mon = {"left": x, "top": y, "width": w, "height": h}
        else:
            mon = self.sct.monitors[1]
        img = np.array(self.sct.grab(mon))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    # -- template matching --------------------------------------------------
    def _template(self, rel_path: str):
        import cv2

        if rel_path not in self._template_cache:
            path = Path(rel_path)
            if not path.is_absolute():
                path = self.cfg["_dir"] / path
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise FileNotFoundError(f"template not found or unreadable: {path}")
            self._template_cache[rel_path] = img
        return self._template_cache[rel_path]

    def find(self, rel_path: str, threshold: float | None = None) -> tuple[int, int] | None:
        """Return the screen-space centre of the best match, or None."""
        import cv2

        threshold = threshold or self.cfg["match_threshold"]
        tpl = self._template(rel_path)
        haystack = self.grab()
        res = cv2.matchTemplate(haystack, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        log.debug("template %s score=%.3f", rel_path, score)
        if score < threshold:
            return None
        h, w = tpl.shape[:2]
        mon = self.sct.monitors[1]
        return mon["left"] + loc[0] + w // 2, mon["top"] + loc[1] + h // 2

    # -- OCR ----------------------------------------------------------------
    def read_number(self, region: tuple[int, int, int, int]) -> int | None:
        import cv2
        import pytesseract

        img = self.grab(region)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Tesseract prefers dark text on light background.
        if bw.mean() < 127:
            bw = cv2.bitwise_not(bw)
        text = pytesseract.image_to_string(
            bw, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        )
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None

    # -- input --------------------------------------------------------------
    def click(self, xy: tuple[int, int], button: str = "left") -> None:
        import pyautogui

        pyautogui.moveTo(xy[0], xy[1], duration=0.08)
        pyautogui.click(button=button)
        time.sleep(self.cfg["delays"]["after_click"])

    def locate(self, spec: dict) -> tuple[int, int] | None:
        """Resolve a locator spec: {template: path} or {x:, y:}."""
        if "template" in spec:
            return self.find(spec["template"], spec.get("threshold"))
        if "x" in spec and "y" in spec:
            return int(spec["x"]), int(spec["y"])
        raise ValueError(f"locator needs 'template' or 'x'/'y': {spec}")


# --------------------------------------------------------------------------- #
# Game interface + implementations
# --------------------------------------------------------------------------- #
class GameError(RuntimeError):
    pass


class RealGame:
    def __init__(self, cfg: dict, screen: Screen) -> None:
        self.cfg = cfg
        self.screen = screen
        self.buttons = cfg["buttons"]
        self.fs_region = tuple(cfg["failstack"]["region"])

    def read_failstack(self) -> int:
        retries = self.cfg["failstack"]["verify_retries"]
        for _ in range(retries):
            val = self.screen.read_number(self.fs_region)
            if val is not None:
                return val
            time.sleep(0.3)
        raise GameError("could not read the failstack counter; check failstack.region")

    def _click_button(self, name: str, optional: bool = False) -> bool:
        spec = self.buttons.get(name)
        if spec is None:
            if optional:
                return False
            raise GameError(f"buttons.{name} is not configured")
        xy = self.screen.locate(spec)
        if xy is None:
            if optional or spec.get("optional"):
                return False
            raise GameError(f"button '{name}' not found on screen")
        self.screen.click(xy)
        return True

    def add_failstack(self) -> None:
        self._click_button("increase_failstack")
        self._click_button("confirm_failstack", optional=True)
        time.sleep(self.cfg["delays"]["after_failstack"])

    def select_item(self, item: Item) -> None:
        loc = item.locator
        spec = None
        per_stage = loc.get("templates") or loc.get("slots")
        if per_stage:
            spec = per_stage.get(item.stage.name)
        if spec is None:
            spec = {k: loc[k] for k in ("template", "x", "y", "threshold") if k in loc}
        if not spec:
            raise GameError(f"{item.name}: no template/slot configured for stage {item.stage.name}")
        xy = self.screen.locate(spec)
        if xy is None:
            raise GameError(f"{item.name} ({item.stage.name}) not found in inventory")
        # Right-clicking an inventory item while the enhancement window is open
        # moves it into the enhancement slot; materials auto-fill.
        self.screen.click(xy, button="right")

    def enhance(self) -> None:
        self._click_button("enhance")
        self._click_button("confirm_enhance", optional=True)
        time.sleep(self.cfg["delays"]["after_enhance"])

    def wait_result(self, fs_before: int, stage: Stage) -> bool | None:
        """True on success, False on failure, None if nothing happened."""
        deadline = time.time() + self.cfg["delays"]["result_timeout"]
        while time.time() < deadline:
            fs = self.read_failstack()
            if fs == 0 and fs_before > 0:
                return True
            if fs > fs_before:
                return False
            time.sleep(0.5)
        return None


class SimGame:
    """Fake game for dry runs: no screen, no input, random outcomes."""

    def __init__(self, cfg: dict, seed: int | None = None) -> None:
        self.cfg = cfg
        self.fs = int(cfg.get("sim", {}).get("start_failstack", 0))
        self.stones = int(cfg.get("sim", {}).get("black_stones", 500))
        self.rng = random.Random(seed)
        self.selected: Item | None = None
        self.pending: bool | None = None
        self.success_rate = cfg.get("sim", {}).get("success_rate", {"PRI": 0.5, "DUO": 0.35})

    def read_failstack(self) -> int:
        return self.fs

    def add_failstack(self) -> None:
        if self.stones <= 0:
            return  # mimics clicking with no stones: counter does not move
        self.stones -= 1
        self.fs += 1

    def select_item(self, item: Item) -> None:
        self.selected = item

    def enhance(self) -> None:
        stage = self.selected.next_stage
        self.pending = self.rng.random() < float(self.success_rate[stage.name])

    def wait_result(self, fs_before: int, stage: Stage) -> bool | None:
        ok, self.pending = self.pending, None
        if ok:
            self.fs = 0
        else:
            self.fs += FAIL_GAIN[stage]
        return ok


# --------------------------------------------------------------------------- #
# Control loop
# --------------------------------------------------------------------------- #
def build_failstack(game, plan: Plan, cfg: dict, controls: Controls) -> int:
    fs = plan.required_fs - plan.stones_to_add
    stuck = 0
    while fs < plan.required_fs:
        controls.check()
        game.add_failstack()
        new_fs = game.read_failstack()
        if new_fs <= fs:
            stuck += 1
            if stuck >= cfg["failstack"]["verify_retries"]:
                raise GameError(
                    f"failstack stuck at {fs} after adding stones; out of Black Stones "
                    "or increase_failstack button misconfigured"
                )
        else:
            stuck = 0
        fs = new_fs
        log.info("  failstack %d/%d", fs, plan.required_fs)
    return fs


def run_loop(game, items: list[Item], cfg: dict, controls: Controls, once: bool = False) -> dict:
    stats = {"attempts": 0, "success": 0, "fail": 0}
    targets = cfg["targets"]
    max_overshoot = cfg["failstack"]["max_overshoot"]

    while True:
        controls.check()
        fs = game.read_failstack()
        decision = choose_next(items, fs, targets, max_overshoot)

        if isinstance(decision, Done):
            log.info("all items finished")
            break
        if isinstance(decision, Halt):
            log.warning("halt: %s", decision.reason)
            break

        plan = decision
        log.info(
            "next: %s %s -> %s at %d FS (current %d, add %d)",
            plan.item.name, plan.item.stage.name, plan.stage.name,
            plan.required_fs, fs, plan.stones_to_add,
        )
        fs = build_failstack(game, plan, cfg, controls)
        controls.check()

        game.select_item(plan.item)
        game.enhance()
        result = game.wait_result(fs, plan.stage)
        stats["attempts"] += 1

        if result is None:
            raise GameError(
                "failstack did not change after pressing Enhance; missing material, "
                "wrong item selected, or enhance button misconfigured"
            )
        if result:
            stats["success"] += 1
            log.info("  SUCCESS: %s is now %s", plan.item.name, plan.stage.name)
        else:
            stats["fail"] += 1
            log.info("  FAIL: %s destroyed, failstack now %d", plan.item.name, game.read_failstack())
        apply_result(items, plan.item, result)

        if once:
            break
    return stats


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_check(cfg: dict) -> int:
    screen = Screen(cfg)
    ok = True
    try:
        fs = screen.read_number(tuple(cfg["failstack"]["region"]))
        print(f"failstack OCR: {fs!r}")
        ok &= fs is not None
    except Exception as exc:  # noqa: BLE001
        print(f"failstack OCR failed: {exc}")
        ok = False

    for name, spec in cfg.get("buttons", {}).items():
        try:
            xy = screen.locate(spec)
        except Exception as exc:  # noqa: BLE001
            xy = f"error: {exc}"
        print(f"button {name:>20}: {xy}")
        if xy is None and not spec.get("optional"):
            ok = False

    for entry in cfg["items"]:
        per_stage = entry.get("templates") or entry.get("slots") or {}
        specs = per_stage or {"any": {k: entry[k] for k in ("template", "x", "y") if k in entry}}
        for stage, spec in specs.items():
            try:
                xy = screen.locate(spec) if spec else None
            except Exception as exc:  # noqa: BLE001
                xy = f"error: {exc}"
            print(f"item {entry['name']} [{stage}]: {xy}")
    print("OK" if ok else "problems found")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "check", "sim"])
    parser.add_argument("--config", default="config.yaml", type=Path)
    parser.add_argument("--once", action="store_true", help="perform a single attempt then exit")
    parser.add_argument("--seed", type=int, help="RNG seed for 'sim'")
    parser.add_argument("--countdown", type=int, default=5, help="seconds before 'run' starts")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)

    if args.command == "check":
        return cmd_check(cfg)

    items = expand_items(cfg["items"])
    log.info("%d item(s) queued; targets: %s", len(items), {k.name: v for k, v in cfg["targets"].items()})
    controls = Controls()

    if args.command == "sim":
        game = SimGame(cfg, seed=args.seed)
    else:
        controls.install(cfg["hotkeys"])
        game = RealGame(cfg, Screen(cfg))
        log.info("focus the game window; starting in %d s", args.countdown)
        for i in range(args.countdown, 0, -1):
            log.info("  %d", i)
            time.sleep(1)

    try:
        stats = run_loop(game, items, cfg, controls, once=args.once)
    except KeyboardInterrupt:
        log.info("stopped by user")
        return 130
    except GameError as exc:
        log.error("%s", exc)
        return 2

    remaining = [f"{i.name}({i.stage.name}->{i.target.name})" for i in items if not i.done]
    log.info("attempts=%d success=%d fail=%d", stats["attempts"], stats["success"], stats["fail"])
    if isinstance(game, SimGame):
        log.info("sim: black stones left=%d, failstack=%d", game.stones, game.fs)
    if remaining:
        log.info("remaining: %s", ", ".join(remaining))
    return 0


if __name__ == "__main__":
    sys.exit(main())
