"""Screen capture, picture matching, OCR and input (X11)."""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger("enchanter.screen")

Region = tuple[int, int, int, int]  # x, y, w, h in absolute screen pixels
Match = tuple[int, int, float]       # centre x, centre y, score


class Screen:
    def __init__(self, cfg) -> None:
        import mss
        import pyautogui

        self.cfg = cfg
        self.sct = getattr(mss, "MSS", mss.mss)()
        self.monitor = self.sct.monitors[1]
        pyautogui.FAILSAFE = True  # mouse into a screen corner aborts
        pyautogui.PAUSE = 0.05
        self._cache: dict[str, object] = {}

    # ---- capture ----------------------------------------------------------
    def grab(self, region: Region | None = None):
        import cv2
        import numpy as np

        if region:
            x, y, w, h = region
            mon = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
        else:
            mon = self.monitor
        return cv2.cvtColor(np.array(self.sct.grab(mon)), cv2.COLOR_BGRA2BGR)

    def full_region(self) -> Region:
        m = self.monitor
        return m["left"], m["top"], m["width"], m["height"]

    # ---- templates --------------------------------------------------------
    def template(self, rel: str):
        import cv2

        if rel not in self._cache:
            path = self.cfg.resolve(rel)
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise FileNotFoundError(f"picture missing or unreadable: {path}")
            self._cache[rel] = img
        return self._cache[rel]

    def save_template(self, name: str, img) -> str:
        import cv2

        path = self.cfg.template_dir() / f"{name}.png"
        cv2.imwrite(str(path), img)
        self._cache.pop(f"templates/{path.name}", None)
        return f"templates/{path.name}"

    def _match(self, rel: str, region: Region | None):
        import cv2

        tpl = self.template(rel)
        region = region or self.full_region()
        hay = self.grab(region)
        if tpl.shape[0] > hay.shape[0] or tpl.shape[1] > hay.shape[1]:
            return None, tpl, region
        return cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED), tpl, region

    def find(self, rel: str, region: Region | None = None, threshold: float | None = None) -> Match | None:
        import cv2

        threshold = threshold if threshold is not None else self.cfg["match_threshold"]
        res, tpl, region = self._match(rel, region)
        if res is None:
            return None
        _, score, _, loc = cv2.minMaxLoc(res)
        log.debug("find %s score=%.3f", rel, score)
        if score < threshold:
            return None
        h, w = tpl.shape[:2]
        return region[0] + loc[0] + w // 2, region[1] + loc[1] + h // 2, float(score)

    def find_all(self, rel: str, region: Region | None = None, threshold: float | None = None) -> list[Match]:
        """All non-overlapping matches above the threshold, best first."""
        import numpy as np

        threshold = threshold if threshold is not None else self.cfg["match_threshold"]
        res, tpl, region = self._match(rel, region)
        if res is None:
            return []
        h, w = tpl.shape[:2]
        ys, xs = np.where(res >= threshold)
        cands = sorted(((float(res[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)
        kept: list[Match] = []
        for score, x, y in cands:
            cx, cy = region[0] + x + w // 2, region[1] + y + h // 2
            if all(abs(cx - kx) >= w * 0.6 or abs(cy - ky) >= h * 0.6 for kx, ky, _ in kept):
                kept.append((cx, cy, score))
        return kept

    # ---- OCR --------------------------------------------------------------
    def read_number(self, region: Region) -> int | None:
        import cv2
        import pytesseract

        gray = cv2.cvtColor(self.grab(region), cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if bw.mean() < 127:  # tesseract wants dark text on light background
            bw = cv2.bitwise_not(bw)
        bw = cv2.copyMakeBorder(bw, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        # No single page-segmentation mode reads every lone digit (7 gets "0", 8 gets "8"),
        # so try several; the whitelist keeps letters out.
        for psm in (7, 8, 6, 10, 13):
            text = pytesseract.image_to_string(bw, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789")
            digits = "".join(ch for ch in text if ch.isdigit())
            if digits:
                return int(digits)
        return None

    # ---- input ------------------------------------------------------------
    def click(self, x: int, y: int, button: str = "left") -> None:
        import pyautogui

        pyautogui.moveTo(x, y, duration=0.08)
        pyautogui.click(button=button)
        time.sleep(self.cfg["delays"]["after_click"])

    def press(self, key: str) -> None:
        import pyautogui

        self.focus_game()
        pyautogui.press(key)
        time.sleep(self.cfg["delays"]["after_key"])

    # ---- window focus (xdotool, optional) --------------------------------
    def game_window_id(self) -> str | None:
        name = self.cfg.get("game_window")
        if not name or not shutil.which("xdotool"):
            return None
        out = subprocess.run(["xdotool", "search", "--name", name], capture_output=True, text=True).stdout
        ids = out.split()
        return ids[-1] if ids else None

    def focus_game(self) -> bool:
        wid = self.game_window_id()
        if not wid:
            return False
        r = subprocess.run(["xdotool", "windowactivate", "--sync", wid], capture_output=True)
        if r.returncode != 0:  # no EWMH window manager: fall back to raw focus
            subprocess.run(["xdotool", "windowraise", wid], capture_output=True)
            subprocess.run(["xdotool", "windowfocus", "--sync", wid], capture_output=True)
        time.sleep(0.2)
        return True
