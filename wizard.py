"""Interactive first-time setup.

Walks the user through capturing every button, the failstack counter and the
accessory icons as screenshots, verifies they can be found again, and writes
config.yaml. No coordinates are ever typed by hand.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import yaml

import selector
from planner import Stage

TEMPLATE_DIR = "templates"


# --------------------------------------------------------------------------- #
# Small prompt helpers
# --------------------------------------------------------------------------- #
def say(msg: str = "") -> None:
    print(msg, flush=True)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{d}]: ").strip().lower()
    if not value:
        return default
    return value.startswith("y")


def ask_choice(prompt: str, choices: list[str], default: str) -> str:
    choices_up = [c.upper() for c in choices]
    while True:
        value = ask(f"{prompt} ({'/'.join(choices_up)})", default).upper()
        if value in choices_up:
            return value
        say(f"  please answer one of {', '.join(choices_up)}")


def ask_int(prompt: str, default: int, lo: int = 0, hi: int = 10_000) -> int:
    while True:
        value = ask(prompt, str(default))
        try:
            n = int(value)
        except ValueError:
            say("  please enter a number")
            continue
        if lo <= n <= hi:
            return n
        say(f"  please enter a number between {lo} and {hi}")


def countdown(seconds: int, what: str) -> None:
    say(f"  switch to the game now; {what} in {seconds}s ...")
    for i in range(seconds, 0, -1):
        print(f"  {i} ", end="\r", flush=True)
        time.sleep(1)
    print("     ", end="\r")


# --------------------------------------------------------------------------- #
# Environment checks
# --------------------------------------------------------------------------- #
def check_environment() -> bool:
    ok = True
    say("Checking the environment ...")

    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    if session == "wayland":
        say("  ! You are on a Wayland session. Screen capture and synthetic clicks need X11.")
        say("    Log out and pick an 'X11' / 'Xorg' session on the login screen, then re-run.")
        ok = False
    elif not os.environ.get("DISPLAY"):
        say("  ! DISPLAY is not set; run this from a terminal inside your desktop session.")
        ok = False
    else:
        say(f"  display: {session} ({os.environ.get('DISPLAY')})")

    for mod, pkg in (("cv2", "opencv-python"), ("mss", "mss"), ("numpy", "numpy"),
                     ("pyautogui", "pyautogui"), ("pytesseract", "pytesseract"),
                     ("pynput", "pynput"), ("yaml", "pyyaml")):
        try:
            __import__(mod)
        except ImportError:
            say(f"  ! python module '{mod}' missing  ->  pip install {pkg}")
            ok = False

    try:
        import tkinter  # noqa: F401
    except ImportError:
        say("  ! tkinter missing  ->  sudo apt install python3-tk")
        ok = False

    if not shutil.which("tesseract"):
        say("  ! tesseract binary missing  ->  sudo apt install tesseract-ocr")
        ok = False

    if ok:
        say("  all good")
    return ok


# --------------------------------------------------------------------------- #
# Capture helpers
# --------------------------------------------------------------------------- #
class Capturer:
    def __init__(self, screen, config_dir: Path) -> None:
        self.screen = screen
        self.config_dir = config_dir
        self.template_dir = config_dir / TEMPLATE_DIR
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self._shot = None

    def fresh_shot(self, delay: int = 3, what: str = "taking a screenshot"):
        countdown(delay, what)
        self._shot = self.screen.grab()
        return self._shot

    def shot(self):
        if self._shot is None:
            return self.fresh_shot()
        return self._shot

    def pick(self, prompt: str, fresh: bool, optional: bool = False):
        """Let the user drag a box; returns (region, crop) or (None, None)."""
        while True:
            img = self.fresh_shot() if fresh else self.shot()
            region = selector.select_region(img, prompt)
            if region is not None:
                return region, selector.crop(img, region)
            if optional and ask_yes("  nothing selected. Skip this one?", default=False):
                return None, None
            if not ask_yes("  nothing selected. Try again?", default=True):
                return None, None
            fresh = ask_yes("  take a new screenshot first?", default=fresh)

    def save_template(self, name: str, crop) -> str:
        import cv2

        path = self.template_dir / f"{name}.png"
        cv2.imwrite(str(path), crop)
        return f"{TEMPLATE_DIR}/{path.name}"

    def capture_template(self, name: str, prompt: str, fresh: bool = False,
                         optional: bool = False) -> str | None:
        region, crop = self.pick(prompt, fresh=fresh, optional=optional)
        if region is None:
            return None
        rel = self.save_template(name, crop)
        say(f"  saved {rel}  ({region[2]}x{region[3]} px)")
        return rel


def slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def capture_item_icon(capturer: Capturer, entry: dict, stage: Stage, fresh: bool) -> str | None:
    """Capture the inventory icon of ``entry`` at ``stage`` and record it in the entry."""
    name = entry["name"]
    rel = capturer.capture_template(
        f"item_{slug(name)}_{stage.name.lower()}",
        f"Drag a box around the inventory icon of {name} ({stage.name}). "
        "Icon only, no slot border or stack number.",
        fresh=fresh,
    )
    if rel is None:
        return None
    templates = entry.setdefault("templates", {})
    if "template" in entry:  # migrate single-template form
        templates.setdefault(entry.get("current", "BASE"), entry.pop("template"))
    templates[stage.name] = rel
    return rel


# --------------------------------------------------------------------------- #
# Wizard
# --------------------------------------------------------------------------- #
def run_wizard(config_path: Path) -> int:
    from enchanter import DEFAULTS, Screen, deep_merge, save_config

    say("=" * 70)
    say(" bdo-enchanter setup")
    say("=" * 70)
    say("This walks you through capturing the buttons and icons the script needs.")
    say("You never type coordinates: you drag boxes on a frozen screenshot.")
    say()
    if not check_environment():
        say("\nFix the items marked '!' and re-run: python enchanter.py setup")
        return 1

    config_dir = config_path.resolve().parent
    raw: dict = {}
    if config_path.exists():
        if ask_yes(f"\n{config_path} exists. Start over?", default=False):
            raw = {}
        else:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
    cfg = deep_merge(DEFAULTS, raw)
    cfg["_dir"] = config_dir
    screen = Screen(cfg)
    cap = Capturer(screen, config_dir)

    say("\nBefore we start, in the game:")
    say("  1. Run BDO in Windowed or Borderless mode (not exclusive Fullscreen).")
    say("  2. Open the Black Spirit menu and choose Enhancement.")
    say("  3. Open your inventory next to it.")
    say("  4. Have Black Stones and your accessories (plus the base copies used as")
    say("     materials) visible in the inventory.")
    say("  5. Make sure the failstack counter currently shows a number (0 is fine).")
    input("\nPress Enter when the game looks like that ...")

    # -- targets ----------------------------------------------------------
    say("\n--- Failstack targets ---")
    targets = raw.get("targets", {})
    pri = ask_int("Failstack for PRI attempts", int(targets.get("PRI", 15)), 0, 500)
    duo = ask_int("Failstack for DUO attempts", int(targets.get("DUO", 40)), 0, 500)
    raw["targets"] = {"PRI": pri, "DUO": duo}

    # -- failstack counter ------------------------------------------------
    say("\n--- Failstack counter ---")
    say("Select the failstack NUMBER in the enhancement window. Keep the box tight")
    say("around the digits with a few pixels of margin; do not include the label.")
    while True:
        region, _ = cap.pick("Drag a box tightly around the failstack NUMBER.", fresh=True)
        if region is None:
            say("  the counter is required.")
            continue
        mon = screen.monitor
        abs_region = [mon["left"] + region[0], mon["top"] + region[1], region[2], region[3]]
        try:
            value = screen.read_number(tuple(abs_region))
        except Exception as exc:  # noqa: BLE001
            say(f"  OCR error: {exc}")
            value = None
        if value is None:
            say("  could not read a number there. Try a tighter or slightly larger box.")
            continue
        if ask_yes(f"  I read '{value}'. Is that the current failstack?"):
            raw.setdefault("failstack", {})["region"] = abs_region
            break
        say("  let's try again; adjust the box so only the digits are inside.")

    # -- buttons ----------------------------------------------------------
    say("\n--- Buttons ---")
    buttons = raw.setdefault("buttons", {})

    say("The button used to raise the failstack by consuming Black Stones.")
    buttons["increase_failstack"] = {"template": cap.capture_template(
        "increase_failstack", "Drag a box around the INCREASE FAILSTACK (Black Stone) button.")}

    say("\nIf pressing that button shows a confirmation popup, press it in the game")
    say("now so the popup is visible, then continue here.")
    if ask_yes("Does a confirmation popup appear when you raise the failstack?", default=False):
        rel = cap.capture_template("confirm_failstack",
                                   "Drag a box around the CONFIRM / OK button of the popup.",
                                   fresh=True, optional=True)
        if rel:
            buttons["confirm_failstack"] = {"template": rel, "optional": True}
        say("  (close the popup now)")
    else:
        buttons.pop("confirm_failstack", None)

    say("\nThe main ENHANCE button.")
    buttons["enhance"] = {"template": cap.capture_template(
        "enhance", "Drag a box around the ENHANCE button.", fresh=True)}

    say("\nSome setups show a confirmation before enhancing (e.g. when an item can be")
    say("destroyed). If you know yours does, open it now; otherwise answer No.")
    if ask_yes("Does a confirmation popup appear when you press Enhance?", default=False):
        rel = cap.capture_template("confirm_enhance",
                                   "Drag a box around the CONFIRM / OK button of the popup.",
                                   fresh=True, optional=True)
        if rel:
            buttons["confirm_enhance"] = {"template": rel, "optional": True}
        say("  (close the popup now without enhancing)")
    else:
        buttons.pop("confirm_enhance", None)

    # -- items ------------------------------------------------------------
    say("\n--- Accessories ---")
    items: list[dict] = []
    if raw.get("items") and ask_yes(f"Keep the {len(raw['items'])} item(s) already configured?"):
        items = raw["items"]
    while True:
        if items:
            say("  configured: " + ", ".join(
                f"{i['name']} x{i.get('count', 1)} ({i.get('current', 'BASE')}->{i.get('target')})"
                for i in items))
            if not ask_yes("Add another accessory type?", default=False):
                break
        name = ask("Accessory name (e.g. Ogre Ring)")
        current = ask_choice("Its current stage", ["BASE", "PRI"], "BASE")
        target = ask_choice("Stage to reach", ["PRI", "DUO"], "DUO" if current == "PRI" else "PRI")
        if Stage[target] <= Stage[current]:
            say("  target must be above the current stage.")
            continue
        count = ask_int("How many copies to enhance (each needs its own base-copy material)", 1, 1, 99)
        entry = {"name": name, "current": current, "target": target, "count": count}
        say(f"  Make sure a {current} {name} is visible in the inventory.")
        if capture_item_icon(cap, entry, Stage[current], fresh=True) is None:
            say("  skipped.")
            continue
        if target == "DUO" and current == "BASE":
            say("  The PRI icon will be captured automatically the first time a PRI")
            say("  succeeds during a run (the script pauses and asks).")
        items.append(entry)
        if not ask_yes("Add another accessory type?", default=False):
            break
    if not items:
        say("No accessories configured; add some later with: python enchanter.py setup")
    raw["items"] = items

    # -- click test -------------------------------------------------------
    raw.setdefault("select_click", "left")
    if items and ask_yes("\nTest which mouse button moves an item into the enhancement slot?"):
        entry = items[0]
        stage = Stage.parse(entry.get("current", "BASE"))
        for button in ("left", "right"):
            countdown(3, f"{button}-clicking {entry['name']}")
            xy = screen.locate(entry["templates"][stage.name])
            if xy is None:
                say("  could not find the icon on screen; skipping the test.")
                break
            screen.click(xy, button=button)
            if ask_yes(f"  Did {entry['name']} move into the enhancement slot?"):
                raw["select_click"] = button
                break
        else:
            say("  neither button worked; check the icon template and re-run the test later.")

    # -- verification -----------------------------------------------------
    say("\n--- Verification ---")
    say("Taking a fresh screenshot and looking for everything that was captured.")
    say("Make sure no popup is open.")
    countdown(3, "verifying")
    problems = 0
    for key, spec in raw["buttons"].items():
        xy = screen.locate(spec)
        say(f"  {key:>20}: {'found at ' + str(xy) if xy else 'NOT FOUND'}")
        if xy is None and not spec.get("optional"):
            problems += 1
    for entry in items:
        for stage, spec in entry.get("templates", {}).items():
            xy = screen.locate({"template": spec})
            say(f"  {entry['name']} [{stage}]: {'found at ' + str(xy) if xy else 'NOT FOUND'}")
            if xy is None:
                problems += 1
    fs = screen.read_number(tuple(raw["failstack"]["region"]))
    say(f"  failstack counter: {fs if fs is not None else 'NOT READABLE'}")
    if fs is None:
        problems += 1

    # -- write ------------------------------------------------------------
    raw.setdefault("hotkeys", {"stop": "f9", "pause": "f10"})
    save_config(config_path, raw)
    say(f"\nWrote {config_path}")
    if problems:
        say(f"{problems} element(s) could not be verified. Re-run setup for those,")
        say("or crop them again with a tighter box, before running for real.")
    say("\nNext steps:")
    say("  python enchanter.py sim          # dry run of the decision logic")
    say("  python enchanter.py run --once   # one real attempt, watch it closely")
    say("  python enchanter.py run          # the whole queue   (F9 stop, F10 pause)")
    return 1 if problems else 0


def capture_missing_item_template(cfg: dict, entry: dict, stage: Stage) -> str | None:
    """Called at runtime when an item needs an icon the config does not have."""
    from enchanter import Screen, save_config

    say("\n" + "-" * 70)
    say(f" {entry['name']} is now {stage.name} and I have no picture of its {stage.name} icon.")
    say(" A screenshot picker will open: drag a box around the icon in the inventory.")
    say("-" * 70)
    input("Press Enter, then switch to the game ...")
    cap = Capturer(Screen(cfg), cfg["_dir"])
    rel = capture_item_icon(cap, entry, stage, fresh=True)
    if rel:
        save_config(cfg["_path"], cfg["_raw"])
    return rel


if __name__ == "__main__":
    sys.exit(run_wizard(Path(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")))
