#!/usr/bin/env python3
"""Auto-enhancer for yellow (boss) accessories in Black Desert Online (Linux/X11).

Builds failstacks with Black Stones to a per-stage target (PRI/DUO), puts the
accessory in the Black Spirit enhancement window and presses Enhance, then
reads the failstack counter to tell success from failure.

Usage:
    python enchanter.py setup [--config config.yaml]   # guided first-time setup
    python enchanter.py check [--config config.yaml]   # verify OCR/templates
    python enchanter.py sim   [--config config.yaml]   # dry run, no input sent
    python enchanter.py run   [--config config.yaml]
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
    "select_click": "left",
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
    if not path.exists():
        raise SystemExit(f"{path} not found. Run:  python enchanter.py setup")
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    cfg = deep_merge(DEFAULTS, raw)
    cfg["_raw"] = raw  # item entries are shared with cfg["items"], so edits persist
    cfg["_path"] = path.resolve()
    cfg["_dir"] = cfg["_path"].parent
    cfg["targets"] = {Stage.parse(k): int(v) for k, v in cfg["targets"].items()}
    if "items" not in cfg:
        raise SystemExit("config: missing required key 'items' (run setup)")
    return cfg


def save_config(path: Path, raw: dict) -> None:
    clean = {k: v for k, v in raw.items() if not k.startswith("_")}
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(clean, fh, sort_keys=False, allow_unicode=True)


# --------------------------------------------------------------------------- #
# Control flags (hotkeys)
# --------------------------------------------------------------------------- #
class Controls:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.paused = threading.Event()
        self._listener = None

    def install(self, hotkeys: dict) -> None:
        try:
            from pynput import keyboard
        except ImportError:
            log.warning("'pynput' not installed; hotkeys disabled (Ctrl+C still works)")
            return

        def key(name: str) -> str:
            name = name.strip().lower()
            return name if name.startswith("<") or len(name) == 1 else f"<{name}>"

        self._listener = keyboard.GlobalHotKeys({
            key(hotkeys["stop"]): self.stop.set,
            key(hotkeys["pause"]): self._toggle_pause,
        })
        self._listener.daemon = True
        self._listener.start()
        log.info("hotkeys: %s = stop, %s = pause/resume", hotkeys["stop"], hotkeys["pause"])

    def _toggle_pause(self) -> None:
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
        self.sct = getattr(mss, "MSS", mss.mss)()
        self.monitor = self.sct.monitors[1]  # primary monitor
        pyautogui.FAILSAFE = True  # slam mouse into a screen corner to abort
        pyautogui.PAUSE = 0.05
        self._template_cache: dict[str, object] = {}

        tess = cfg.get("tesseract_cmd")
        if tess:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = tess

    # -- capture ------------------------------------------------------------
    def grab(self, region: tuple[int, int, int, int] | None = None):
        """Screenshot of the primary monitor (or an absolute region of it) as BGR."""
        import cv2
        import numpy as np

        if region:
            x, y, w, h = region
            mon = {"left": x, "top": y, "width": w, "height": h}
        else:
            mon = self.monitor
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
        """Return the absolute screen centre of the best match, or None."""
        import cv2

        threshold = threshold or self.cfg["match_threshold"]
        tpl = self._template(rel_path)
        haystack = self.grab()
        if tpl.shape[0] > haystack.shape[0] or tpl.shape[1] > haystack.shape[1]:
            return None
        res = cv2.matchTemplate(haystack, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        log.debug("template %s score=%.3f", rel_path, score)
        if score < threshold:
            return None
        h, w = tpl.shape[:2]
        return self.monitor["left"] + loc[0] + w // 2, self.monitor["top"] + loc[1] + h // 2

    # -- OCR ----------------------------------------------------------------
    def read_number(self, region: tuple[int, int, int, int]) -> int | None:
        import cv2
        import pytesseract

        img = self.grab(region)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Tesseract prefers dark text on a light background.
        if bw.mean() < 127:
            bw = cv2.bitwise_not(bw)
        bw = cv2.copyMakeBorder(bw, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        # psm 8 (single word) copes with lone digits; psm 7/13 cover multi-digit
        # counters where 8 occasionally drops a digit.
        for psm in (8, 7, 13):
            text = pytesseract.image_to_string(
                bw, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789"
            )
            digits = "".join(ch for ch in text if ch.isdigit())
            if digits:
                return int(digits)
        return None

    # -- input --------------------------------------------------------------
    def click(self, xy: tuple[int, int], button: str = "left") -> None:
        import pyautogui

        pyautogui.moveTo(xy[0], xy[1], duration=0.08)
        pyautogui.click(button=button)
        time.sleep(self.cfg["delays"]["after_click"])

    def locate(self, spec) -> tuple[int, int] | None:
        """Resolve a locator: a template path, {template: path} or {x:, y:}."""
        if isinstance(spec, str):
            return self.find(spec)
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


def item_locator(entry: dict, stage: Stage):
    """Locator spec for an item entry at a stage, or None if not configured."""
    per_stage = entry.get("templates") or entry.get("slots")
    if per_stage and stage.name in per_stage:
        return per_stage[stage.name]
    single = {k: entry[k] for k in ("template", "x", "y", "threshold") if k in entry}
    if single and Stage.parse(entry.get("current", "BASE")) == stage:
        return single
    return None


class RealGame:
    def __init__(self, cfg: dict, screen: Screen, interactive: bool = True) -> None:
        self.cfg = cfg
        self.screen = screen
        self.interactive = interactive
        self.buttons = cfg.get("buttons", {})
        if "region" not in cfg.get("failstack", {}):
            raise GameError("failstack.region missing; run setup")
        self.fs_region = tuple(cfg["failstack"]["region"])

    def read_failstack(self) -> int:
        retries = self.cfg["failstack"]["verify_retries"]
        for _ in range(retries):
            val = self.screen.read_number(self.fs_region)
            if val is not None:
                return val
            time.sleep(0.3)
        raise GameError("could not read the failstack counter; re-run setup")

    def _click_button(self, name: str, optional: bool = False) -> bool:
        spec = self.buttons.get(name)
        if spec is None:
            if optional:
                return False
            raise GameError(f"buttons.{name} is not configured; run setup")
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
        entry = item.locator
        spec = item_locator(entry, item.stage)
        if spec is None and self.interactive:
            from wizard import capture_missing_item_template

            if capture_missing_item_template(self.cfg, entry, item.stage):
                spec = item_locator(entry, item.stage)
        if spec is None:
            raise GameError(f"{item.name}: no picture of its {item.stage.name} icon; run setup")
        xy = self.screen.locate(spec)
        if xy is None:
            raise GameError(f"{item.name} ({item.stage.name}) not found in inventory")
        self.screen.click(xy, button=self.cfg["select_click"])

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
        sim = cfg.get("sim") or {}
        self.fs = int(sim.get("start_failstack", 0))
        self.stones = int(sim.get("black_stones", 500))
        self.rng = random.Random(seed)
        self.selected: Item | None = None
        self.pending: bool | None = None
        self.success_rate = sim.get("success_rate", {"PRI": 0.5, "DUO": 0.35})

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
                    "or the increase_failstack picture no longer matches"
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
                "wrong item selected, or the enhance picture no longer matches"
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
    region = cfg.get("failstack", {}).get("region")
    if region:
        try:
            fs = screen.read_number(tuple(region))
            print(f"failstack OCR: {fs!r}")
            ok &= fs is not None
        except Exception as exc:  # noqa: BLE001
            print(f"failstack OCR failed: {exc}")
            ok = False
    else:
        print("failstack region not configured")
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
        for stage in Stage:
            spec = item_locator(entry, stage)
            if spec is None:
                continue
            try:
                xy = screen.locate(spec)
            except Exception as exc:  # noqa: BLE001
                xy = f"error: {exc}"
            print(f"item {entry['name']} [{stage.name}]: {xy}")
    print("OK" if ok else "problems found; run: python enchanter.py setup")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["setup", "run", "check", "sim"])
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

    if args.command == "setup":
        from wizard import run_wizard

        return run_wizard(args.config)

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
        try:
            game = RealGame(cfg, Screen(cfg))
        except GameError as exc:
            log.error("%s", exc)
            return 2
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
