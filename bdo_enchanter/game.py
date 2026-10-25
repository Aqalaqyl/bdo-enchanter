"""The real game, driven through the screen: recorded menu flows + pictures."""
from __future__ import annotations

import logging
import time

from .config import Stage
from .phases import GameError
from .screen import Match, Screen

log = logging.getLogger("enchanter.game")


class FlowRunner:
    """Plays recorded menu flows (key presses, picture clicks, waits)."""

    def __init__(self, cfg, screen: Screen, check=lambda: None) -> None:
        self.cfg = cfg
        self.screen = screen
        self.check = check  # called between steps so hotkeys can stop/pause

    def run_step(self, step: dict) -> None:
        if "key" in step:
            self.screen.press(str(step["key"]))
        elif "click" in step:
            m = self.screen.find(step["click"])
            if m is None:
                if step.get("optional"):
                    log.debug("optional picture %s not on screen; skipping", step["click"])
                    return
                raise GameError(f"picture {step['click']} not found on screen")
            self.screen.click(m[0], m[1], step.get("button", "left"))
        elif "wait" in step:
            time.sleep(float(step["wait"]))
        else:
            raise GameError(f"unknown flow step {step}")

    def run_flow(self, name: str) -> None:
        for step in self.cfg["flows"].get(name, []):
            self.check()
            self.run_step(step)


class RealGame(FlowRunner):
    def __init__(self, cfg, screen: Screen, check=lambda: None, interactive: bool = True) -> None:
        super().__init__(cfg, screen, check)
        self.interactive = interactive
        for key in ("inventory_region", "anchors"):
            if key not in cfg.raw:
                raise GameError(f"'{key}' missing from config; run ./enchanter setup")
        if "region" not in cfg["failstack"]:
            raise GameError("failstack.region missing from config; run ./enchanter setup")
        self.inventory = tuple(cfg["inventory_region"])
        self.fs_region = tuple(cfg["failstack"]["region"])
        menu = cfg["failstack"].get("menu_region")
        if menu:
            self.fs_menu_region = tuple(menu)
        elif not cfg["flows"].get("open_failstack_menu"):
            self.fs_menu_region = self.fs_region  # stones consumed in the same window: main counter is visible
        else:
            self.fs_menu_region = None

    # ---- enhancement window ----------------------------------------------
    def enhancement_open(self) -> bool:
        return self.screen.find(self.cfg["anchors"]["enhancement_open"]) is not None

    def ensure_enhancement_open(self) -> None:
        if self.enhancement_open():
            return
        log.info("enhancement window not visible; opening it")
        self.run_flow("open_enhancement")
        time.sleep(0.5)
        if not self.enhancement_open():
            raise GameError("enhancement window still not visible after the open_enhancement flow")

    # ---- failstack --------------------------------------------------------
    def _read(self, region, what: str) -> int:
        for _ in range(4):
            v = self.screen.read_number(region)
            if v is not None:
                return v
            time.sleep(0.3)
        raise GameError(f"could not read the {what}; re-run setup if the UI moved")

    def read_failstack(self) -> int:
        return self._read(self.fs_region, "failstack counter")

    def raise_failstack_to(self, target: int) -> int:
        fs = self.read_failstack()
        for _round in range(3):
            self.run_flow("open_failstack_menu")
            time.sleep(0.3)
            seen = self._read(self.fs_menu_region, "failstack counter in the menu") if self.fs_menu_region else fs
            stuck = 0
            while seen < target:
                self.check()
                self.run_flow("add_failstack")
                time.sleep(self.cfg["delays"]["after_failstack"])
                if self.fs_menu_region:
                    now = self._read(self.fs_menu_region, "failstack counter in the menu")
                    if now <= seen:
                        stuck += 1
                        if stuck >= 3:
                            self.run_flow("close_failstack_menu")
                            raise GameError(
                                f"failstack stopped increasing at {now}: out of Black Stones, "
                                "cap reached, or the add_failstack pictures no longer match")
                    else:
                        stuck = 0
                    seen = now
                else:
                    seen += 1  # verified after closing the menu
                log.info("  failstack %d/%d", seen, target)
            self.run_flow("close_failstack_menu")
            time.sleep(0.3)
            new_fs = self.read_failstack()
            if new_fs >= target:
                return new_fs
            if new_fs <= fs:
                raise GameError(
                    f"failstack still {new_fs} after consuming stones: out of Black Stones, "
                    "cap reached, or the add_failstack pictures no longer match")
            fs = new_fs
        return fs

    # ---- items ------------------------------------------------------------
    def locate_items(self, item: dict) -> dict[Stage, list[Match]]:
        """Matches per stage inside the inventory area, each slot assigned to one stage only.

        A BASE picture also matches PRI/DUO icons (they differ only by a small
        badge), so every slot goes to whichever stage picture scores highest.
        """
        found: list[tuple[float, int, int, Stage, int]] = []
        for stage in Stage:
            rel = self.cfg.item_template(item, stage)
            if not rel:
                continue
            h, w = self.screen.template(rel).shape[:2]
            for x, y, score in self.screen.find_all(rel, self.inventory):
                found.append((score, x, y, stage, min(w, h)))
        found.sort(reverse=True)
        kept: list[tuple[int, int, Stage]] = []
        result: dict[Stage, list[Match]] = {s: [] for s in Stage}
        for score, x, y, stage, size in found:
            if any(abs(x - kx) < size * 0.6 and abs(y - ky) < size * 0.6 for kx, ky, _ in kept):
                continue
            kept.append((x, y, stage))
            result[stage].append((x, y, score))
        return result

    def count_items(self, item: dict) -> dict[Stage, int]:
        return {s: len(m) for s, m in self.locate_items(item).items()}

    def place_item(self, item: dict, stage: Stage) -> bool:
        matches = self.locate_items(item).get(stage, [])
        if not matches:
            return False
        x, y, _ = matches[0]
        self.screen.click(x, y, self.cfg["select_click"])
        return True

    # ---- enhance ----------------------------------------------------------
    def enhance_and_wait(self, fs_before: int, stage: Stage) -> bool | None:
        self.run_flow("enhance")
        time.sleep(self.cfg["delays"]["after_enhance"])
        deadline = time.time() + self.cfg["delays"]["result_timeout"]
        while time.time() < deadline:
            fs = self.read_failstack()
            if fs == 0 and fs_before > 0:
                return True
            if fs > fs_before:
                return False
            time.sleep(0.5)
        return None

    def ensure_template(self, item: dict, stage: Stage) -> None:
        if self.cfg.item_template(item, stage) or not self.interactive:
            return
        from .wizard import capture_item_picture_now

        capture_item_picture_now(self.cfg, self.screen, item, stage)
