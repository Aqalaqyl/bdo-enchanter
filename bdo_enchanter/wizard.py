"""Guided setup: records menu flows and captures pictures; writes config.yaml."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from . import picker
from .config import Config, Stage

# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #
def say(msg: str = "") -> None:
    print(msg, flush=True)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        v = input(f"{prompt}{suffix}: ").strip()
        if v:
            return v
        if default is not None:
            return default


def ask_yes(prompt: str, default: bool = True) -> bool:
    v = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not v else v.startswith("y")


def ask_int(prompt: str, default: int, lo: int = 0, hi: int = 9999) -> int:
    while True:
        try:
            n = int(ask(prompt, str(default)))
        except ValueError:
            say("  please enter a number")
            continue
        if lo <= n <= hi:
            return n
        say(f"  please enter a number between {lo} and {hi}")


def ask_choice(prompt: str, choices: dict[str, str], default: str) -> str:
    legend = "  ".join(f"[{k}] {v}" for k, v in choices.items())
    while True:
        v = input(f"{prompt}  {legend}  [{default}]: ").strip().lower() or default
        if v in choices:
            return v


def slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #
def check_environment() -> bool:
    ok = True
    say("Checking the environment ...")
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    if session == "wayland":
        say("  ! Wayland session detected. Screen capture and clicks need X11: log out and")
        say("    choose an 'X11' / 'Xorg' session on the login screen, then re-run.")
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
            say(f"  ! python module '{mod}' missing  ->  .venv/bin/pip install {pkg}")
            ok = False
    try:
        import tkinter  # noqa: F401
    except ImportError:
        say("  ! tkinter missing  ->  sudo apt install python3-tk")
        ok = False
    if not shutil.which("tesseract"):
        say("  ! tesseract missing  ->  sudo apt install tesseract-ocr")
        ok = False
    if not shutil.which("xdotool"):
        say("  - xdotool missing (optional, lets me focus the game for you) -> sudo apt install xdotool")
    if ok:
        say("  all good")
    return ok


# --------------------------------------------------------------------------- #
# capture helpers
# --------------------------------------------------------------------------- #
class Studio:
    """Screenshots, region picking and flow recording against the live game."""

    def __init__(self, cfg: Config, screen) -> None:
        self.cfg = cfg
        self.screen = screen

    def to_game(self, what: str = "taking a screenshot", seconds: int = 3) -> None:
        if self.screen.focus_game():
            time.sleep(0.6)
            return
        say(f"  switch to the game now; {what} in {seconds}s ...")
        for i in range(seconds, 0, -1):
            print(f"  {i} ", end="\r", flush=True)
            time.sleep(1)
        print("     ", end="\r")

    def shot(self):
        self.to_game()
        return self.screen.grab()

    def pick(self, prompt: str, required: bool = True):
        """-> (absolute_region, crop) or (None, None)."""
        while True:
            img = self.shot()
            region = picker.select_region(img, prompt)
            time.sleep(0.4)  # let the X server repaint after the picker window closes
            if region is not None:
                mon = self.screen.monitor
                abs_region = (mon["left"] + region[0], mon["top"] + region[1], region[2], region[3])
                return abs_region, picker.crop(img, region)
            if required:
                say("  nothing selected; let's try again.")
                continue
            if ask_yes("  nothing selected. Skip this?", default=False):
                return None, None

    def picture(self, name: str, prompt: str, required: bool = True) -> str | None:
        region, crop = self.pick(prompt, required)
        if region is None:
            return None
        rel = self.screen.save_template(name, crop)
        say(f"  saved {rel} ({region[2]}x{region[3]} px)")
        return rel

    def number_region(self, prompt: str, what: str):
        while True:
            region, _ = self.pick(prompt)
            value = self.screen.read_number(region)
            if value is None:
                say(f"  could not read a number there; draw the box tighter around the digits "
                    "(a few pixels of margin, no label).")
                continue
            if ask_yes(f"  I read '{value}'. Is that the {what}?"):
                return list(region), value
            say("  let's try again.")

    # ---- flow recorder ----------------------------------------------------
    def record_flow(self, name: str, intro: str, perform: bool) -> list[dict]:
        say()
        say(f"--- Recording: {name} ---")
        say(intro)
        if perform:
            say("I will perform each step right after you describe it, so the game follows along.")
        else:
            say("I will NOT perform these steps.")
        steps: list[dict] = []
        while True:
            choice = ask_choice(f"  step {len(steps) + 1}",
                                {"k": "press a key", "c": "click a picture", "w": "wait", "d": "done"}, "d")
            if choice == "d":
                break
            if choice == "k":
                key = ask("  key to press (e.g. ,  i  esc  enter  f5)")
                steps.append({"key": key})
                if perform:
                    self.to_game(f"pressing '{key}'")
                    self.screen.press(key)
                    say(f"  pressed '{key}'")
            elif choice == "c":
                rel = self.picture(f"{name}_{len(steps) + 1}", f"[{name}] Drag a box around the thing to CLICK next.")
                step = {"click": rel}
                if ask_yes("  is this click optional (skip silently when the picture is not on screen)?", default=False):
                    step["optional"] = True
                steps.append(step)
                if perform:
                    m = self.screen.find(rel)
                    if m is None:
                        say("  ! I cannot find that picture right now; clicking skipped.")
                    else:
                        self.screen.click(m[0], m[1])
                        say(f"  clicked at {m[0]},{m[1]}")
            elif choice == "w":
                secs = float(ask("  seconds to wait", "1"))
                steps.append({"wait": secs})
                if perform:
                    time.sleep(secs)
        say(f"  {name}: {len(steps)} step(s)")
        return steps


# --------------------------------------------------------------------------- #
# the wizard
# --------------------------------------------------------------------------- #
def run_wizard(config_path: Path) -> int:
    from .screen import Screen

    say("=" * 72)
    say(" bdo-enchanter setup")
    say("=" * 72)
    say("I will learn your menus by recording them and learn your buttons and items")
    say("from pictures you draw boxes around. Nothing needs to be typed as coordinates.")
    say()
    if not check_environment():
        say("\nFix the lines marked '!' and run ./enchanter setup again.")
        return 1

    cfg = Config.load(config_path) if config_path.exists() else Config(config_path, {})
    raw = cfg.raw
    if config_path.exists() and ask_yes(f"\n{config_path} exists. Start over from scratch?", default=False):
        raw.clear()
    screen = Screen(cfg)
    st = Studio(cfg, screen)

    # -- game window ------------------------------------------------------
    say("\n--- Game window ---")
    if screen.game_window_id():
        say(f"  found a window matching '{cfg['game_window']}'; I can focus it for you.")
    else:
        say(f"  no window matching '{cfg['game_window']}' found (or xdotool missing).")
        title = ask("  part of the game window title, or '-' to use countdowns instead", cfg["game_window"])
        raw["game_window"] = None if title == "-" else title
        cfg.save()
        if screen.game_window_id():
            say("  found it.")
        else:
            say("  I will give you a 3 second countdown to switch to the game before each action.")

    # -- targets ----------------------------------------------------------
    say("\n--- Failstack targets ---")
    t = raw.get("targets", {})
    raw["targets"] = {"PRI": ask_int("Failstack before a PRI attempt", int(t.get("PRI", 15)), 0, 500),
                      "DUO": ask_int("Failstack before a DUO attempt", int(t.get("DUO", 40)), 0, 500)}

    say("\nIn the game: run it in Windowed or Borderless mode, be somewhere safe, and")
    say("CLOSE every menu so you see the normal game view.")
    input("Press Enter when ready ...")

    # -- open enhancement -------------------------------------------------
    flows = raw.setdefault("flows", {})
    if flows.get("open_enhancement") and ask_yes("\nKeep the recorded 'open enhancement window' steps?"):
        from .game import FlowRunner

        st.to_game("opening the enhancement window")
        FlowRunner(cfg, screen).run_flow("open_enhancement")
    else:
        flows["open_enhancement"] = st.record_flow(
            "open_enhancement",
            "How do you get from the normal view to the enhancement window with your\n"
            "inventory visible? Typically: press ',' (Black Spirit), click 'Enhancement',\n"
            "and press 'i' if the inventory does not open by itself.", perform=True)

    say("\nThe enhancement window and inventory should be on screen now.")
    input("Press Enter to continue ...")

    # -- anchor -----------------------------------------------------------
    say("\n--- Enhancement window picture ---")
    say("I need a picture that is ONLY visible while the enhancement window is open and")
    say("that never changes: e.g. the window title or the 'Enhance' label. Avoid numbers.")
    raw.setdefault("anchors", {})["enhancement_open"] = st.picture(
        "enhancement_open", "Drag a box around a fixed part of the enhancement window (e.g. its title).")

    # -- failstack counter ------------------------------------------------
    say("\n--- Failstack counter ---")
    region, fs_now = st.number_region("Drag a tight box around the failstack NUMBER.", "current failstack")
    raw.setdefault("failstack", {})["region"] = region

    # -- inventory area ---------------------------------------------------
    say("\n--- Inventory area ---")
    say("Draw a box around the inventory grid where your accessories and materials sit.")
    say("Keep the enhancement slot OUT of the box so I never click the item already in it.")
    region, _ = st.pick("Drag a box around the INVENTORY GRID (not the enhancement slot).")
    raw["inventory_region"] = list(region)

    # -- items ------------------------------------------------------------
    say("\n--- Accessories ---")
    items: list[dict] = raw.get("items") or []
    if items and not ask_yes(f"Keep the {len(items)} configured accessory type(s)?"):
        items = []
    while True:
        if items:
            say("  configured: " + ", ".join(f"{i['name']} (PRI goal {i.get('pri_count', 1)})" for i in items))
            if not ask_yes("Add another accessory type?", default=False):
                break
        name = ask("Accessory name", "Deboreka Ring" if not items else None)
        entry = {"name": name,
                 "pri_count": ask_int(f"How many {name} do you want at PRI", 1, 1, 99),
                 "templates": {}}
        say("  Box the icon of a plain (unenhanced) copy. Include the corner where the")
        say("  I / II enhancement badge appears so PRI/DUO copies can be told apart.")
        entry["templates"]["BASE"] = st.picture(f"item_{slug(name)}_base", f"Drag a box around a BASE {name} icon.")
        for stage in (Stage.PRI, Stage.DUO):
            if ask_yes(f"  do you already have a {stage.name} {name} visible in the inventory?", default=False):
                rel = st.picture(f"item_{slug(name)}_{stage.name.lower()}",
                                 f"Drag a box around a {stage.name} {name} icon.", required=False)
                if rel:
                    entry["templates"][stage.name] = rel
        items.append(entry)
        if not ask_yes("Add another accessory type?", default=False):
            break
    raw["items"] = items
    if items:
        say("  (missing PRI/DUO pictures are captured automatically after the first success)")

    # -- failstack menu + stone ------------------------------------------
    say("\n--- Consuming Black Stones for failstacks ---")
    flows["open_failstack_menu"] = st.record_flow(
        "open_failstack_menu",
        "If Black Stones are consumed in a separate menu or popup, record how to open it\n"
        "from the enhancement window. If it happens right in this window, choose [d] now.",
        perform=True)
    menu_open = bool(flows["open_failstack_menu"])
    fs_cfg = raw["failstack"]
    fs_cfg.pop("menu_region", None)
    if menu_open and ask_yes("Is the failstack number visible inside this menu?"):
        fs_cfg["menu_region"], _ = st.number_region(
            "Drag a tight box around the failstack NUMBER shown in this menu.", "current failstack")

    flows["add_failstack"] = st.record_flow(
        "add_failstack",
        "Record what consumes ONE Black Stone for +1 failstack (the button, plus a confirm\n"
        "button if one appears). One stone really will be used now.", perform=True)
    performed_stone = bool(flows["add_failstack"])

    if menu_open:
        flows["close_failstack_menu"] = st.record_flow(
            "close_failstack_menu",
            "Record how to get back to the enhancement window (close button or 'esc').", perform=True)
    else:
        flows["close_failstack_menu"] = []

    time.sleep(0.5)
    st.to_game("checking the failstack counter")
    fs_after = screen.read_number(tuple(fs_cfg["region"]))
    if fs_after is not None and fs_after > fs_now:
        say(f"  failstack went {fs_now} -> {fs_after}. Stone consumption works.")
    elif performed_stone:
        say(f"  ! failstack counter reads {fs_after} (was {fs_now}); the stone may not have been")
        say("    consumed or the counter is somewhere else. You can re-run setup to fix this.")

    # -- enhance ----------------------------------------------------------
    flows["enhance"] = st.record_flow(
        "enhance",
        "Record the ENHANCE button (and, if your UI shows one after it, the confirm button;\n"
        "mark the confirm click as optional). Nothing is pressed now.", perform=False)

    # -- click test -------------------------------------------------------
    raw.setdefault("select_click", "left")
    if items and ask_yes("\nTest which mouse button moves an item into the enhancement slot?"):
        entry = items[0]
        for button in ("left", "right"):
            st.to_game(f"{button}-clicking a {entry['name']}")
            m = screen.find(entry["templates"]["BASE"], tuple(raw["inventory_region"]))
            if m is None:
                say("  could not find the icon in the inventory area; skipping this test.")
                break
            screen.click(m[0], m[1], button)
            if ask_yes(f"  did the {entry['name']} move into the enhancement slot?"):
                raw["select_click"] = button
                break
        else:
            say("  neither worked; check the icon picture and inventory box, then re-run setup.")

    # -- verify + save ----------------------------------------------------
    say("\n--- Verification ---")
    st.to_game("verifying")
    problems = 0
    for key, rel in raw["anchors"].items():
        m = screen.find(rel)
        say(f"  anchor {key}: {'found' if m else 'NOT FOUND'}")
        problems += m is None
    for fname, steps in flows.items():
        for s in steps:
            if "click" in s:
                m = screen.find(s["click"])
                say(f"  {fname}: {s['click']}: {'found' if m else ('not on screen (ok, other menu)' if fname != 'enhance' else 'NOT FOUND')}")
                problems += m is None and fname == "enhance" and not s.get("optional")
    for entry in items:
        for stage, rel in entry["templates"].items():
            n = len(screen.find_all(rel, tuple(raw["inventory_region"])))
            say(f"  {entry['name']} [{stage}]: {n} match(es) in the inventory area")
            problems += n == 0
    v = screen.read_number(tuple(fs_cfg["region"]))
    say(f"  failstack counter: {v if v is not None else 'NOT READABLE'}")
    problems += v is None

    cfg.save()
    say(f"\nWrote {cfg.path}")
    if problems:
        say(f"{problems} thing(s) could not be verified; re-run ./enchanter setup to redo them.")
    say("\nNext:")
    say("  ./enchanter check              # look at everything without clicking")
    say("  ./enchanter pri --attempts 1   # one real PRI attempt, watch it")
    say("  ./enchanter pri                # until each type has its PRI goal")
    say("  ./enchanter duo                # later: take every PRI copy to DUO")
    say("  (F9 stops, F10 pauses; mouse into a screen corner aborts)")
    return 1 if problems else 0


def capture_item_picture_now(cfg: Config, screen, item: dict, stage: Stage) -> str | None:
    """Runtime: an item just reached ``stage`` and we have no picture of that icon."""
    say("\n" + "-" * 72)
    say(f" {item['name']} just reached {stage.name} and I have no picture of its {stage.name} icon.")
    say(" Make sure it is visible in the inventory area, then press Enter: a screenshot")
    say(" picker opens; drag a box around that icon (include the badge corner).")
    say("-" * 72)
    input("Press Enter ...")
    st = Studio(cfg, screen)
    rel = st.picture(f"item_{slug(item['name'])}_{stage.name.lower()}",
                     f"Drag a box around the {stage.name} {item['name']} icon.")
    item.setdefault("templates", {})[stage.name] = rel
    cfg.save()
    return rel
