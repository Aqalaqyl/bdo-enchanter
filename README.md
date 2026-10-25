# bdo-enchanter

Auto-enhancer for **yellow (boss) accessories** in Black Desert Online on
**Linux (X11)**. It builds failstacks by consuming Black Stones up to a
per-stage target, puts the accessory in the Black Spirit enhancement window,
presses Enhance, and reads the failstack counter to tell success from failure.

Default targets: **PRI at 15 FS**, **DUO at 40 FS**.

> **Warning.** This is a screen-reading macro (picture matching + OCR +
> synthetic mouse clicks). Third-party automation violates Pearl Abyss'
> Terms of Service and can get an account banned. Use at your own risk and
> never leave it running unattended. Yellow accessories are destroyed on a
> failed enhancement; a bad picture can make it click the wrong item.

## Quick start

```bash
git clone <this repo> && cd bdo-enchanter
./install.sh                          # apt packages + .venv with all Python deps
.venv/bin/python enchanter.py setup   # guided setup, ~5 minutes
.venv/bin/python enchanter.py run --once
```

The game must run in **Windowed or Borderless** mode (not exclusive
fullscreen) on an **X11** session; Wayland cannot be captured or clicked.

## The guided setup

`enchanter.py setup` walks you through everything and writes `config.yaml`.
You never type a coordinate. For each element it takes a screenshot, shows it
frozen full-screen, and you **drag a box** around the thing it asks for:

1. Environment check (X11, Tesseract, Python modules) with fix hints.
2. Failstack targets for PRI / DUO (defaults 15 / 40).
3. The failstack **number** — it immediately OCRs your box and asks
   "I read 17, correct?" until it reads right.
4. The **Increase Failstack** (Black Stone) button and **Enhance** button,
   plus optional confirmation buttons if your UI shows popups.
5. Your accessories: name, current stage, target, how many copies, and a box
   around the inventory icon.
6. A click test to learn whether left or right click moves an item into the
   enhancement slot.
7. Verification: a fresh screenshot in which every captured picture must be
   found again.

Pictures are stored in `templates/`. If an item reaches PRI during a run and
no PRI icon exists yet, the run pauses, the same picker opens, and the new
picture is saved to the config for next time.

## Commands

```bash
python enchanter.py setup            # (re)run the wizard; keeps existing items if you want
python enchanter.py check            # find every picture + read the counter, report problems
python enchanter.py sim --seed 1     # dry run of the decision logic against a simulated game
python enchanter.py run --once       # one real attempt
python enchanter.py run              # the whole queue
```

While running: **F9** stops, **F10** pauses/resumes, and moving the mouse into
a screen corner aborts (pyautogui fail-safe).

## How it decides what to do

`planner.py` holds the logic (no game code, fully unit-tested):

- Each configured accessory expands to `count` physical items with a current
  stage (`BASE`/`PRI`) and a target (`PRI`/`DUO`).
- Before every attempt it reads the current failstack and picks the attempt
  that uses it best: the highest-requirement attempt that already fits,
  otherwise the lowest-requirement attempt, building the difference with
  Black Stones.
- Success advances the item's stage (the game resets FS to 0); failure drops
  the item from the queue (it was destroyed).
- If the stack is higher than any usable target by more than
  `failstack.max_overshoot` (e.g. 42 after a DUO fail with only PRI attempts
  left) it stops instead of wasting the stack.
- It stops on anything it cannot verify: unreadable counter, counter not
  moving after a stone, counter not changing after Enhance.

## Layout

| File | Purpose |
| --- | --- |
| `enchanter.py` | CLI, screen capture / OCR / clicking, control loop, simulator |
| `wizard.py` | Guided setup and runtime capture of missing item pictures |
| `selector.py` | Full-screen drag-a-box region picker (tkinter) |
| `planner.py` | Pure decision logic (which item, which stage, how many stones) |
| `install.sh` | apt + virtualenv installer for Debian/Ubuntu-based systems |
| `config.example.yaml` | Annotated example of the generated configuration |
| `tests/` | Unit tests: `python -m pytest` |

## Limitations

- Only `BASE -> PRI -> DUO` on yellow accessories. Higher stages, Valks
  stacks, Cron Stones and failstack storage are out of scope.
- Result detection relies on the failstack counter (0 = success, higher =
  fail); it does not read the success/fail popup.
- Any UI-scale, resolution or patch change means re-running `setup`.
- Multi-monitor: the game must be on the primary monitor.
