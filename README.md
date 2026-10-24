# bdo-enchanter

Auto-enhancer for **yellow (boss) accessories** in Black Desert Online.
It builds failstacks by consuming Black Stones up to a per-stage target,
right-clicks the accessory into the Black Spirit enhancement window, presses
Enhance, and reads the failstack counter to tell success from failure.

Default targets: **PRI at 15 FS**, **DUO at 40 FS**.

> **Warning.** This is a screen-reading macro (OpenCV template matching + OCR +
> synthetic mouse clicks). Third-party automation violates Pearl Abyss'
> Terms of Service and can get an account banned. Use at your own risk, and
> never leave it running unattended. Yellow accessories are destroyed on a
> failed enhancement; a misconfigured template can click the wrong item.

## How it decides what to do

`planner.py` holds the logic (no game code, fully unit-tested):

- Each config entry expands to `count` physical items with a current stage
  (`BASE`/`PRI`) and a target (`PRI`/`DUO`).
- Before every attempt it reads the current failstack and picks the attempt
  that uses it best: the highest-requirement attempt that already fits,
  otherwise the lowest-requirement attempt, building the difference with
  Black Stones.
- Success advances the item's stage (and resets FS to 0 in game); failure
  removes the item from the queue (it was destroyed).
- If the stack is higher than any usable target by more than
  `failstack.max_overshoot` (e.g. you are on 42 after a DUO fail and only PRI
  attempts remain) it stops instead of wasting the stack.
- It stops on anything it cannot verify: unreadable counter, counter not
  moving after a stone, counter not changing after Enhance.

## Setup (Windows)

1. Python 3.10+ and `pip install -r requirements.txt`.
2. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and
   point `tesseract_cmd` in the config at `tesseract.exe`.
3. `copy config.example.yaml config.yaml` and edit it:
   - `failstack.region`: `[x, y, w, h]` of the failstack number in the
     enhancement window. Keep it tight around the digits.
   - `buttons.*`: crop screenshots (Snipping Tool, 100% scale, same
     resolution/UI scale you play at) of the **Increase Failstack** button,
     the **Enhance** button and any confirmation button into `templates/`,
     or give fixed `{x, y}` coordinates.
   - `items`: one entry per accessory type with a template per stage
     (`BASE` and `PRI` icons differ by the enhancement badge; separate
     templates stop the script from grabbing a base copy you meant as material).
4. Open the Black Spirit enhancement window and your inventory, make sure
   Black Stones and the base-copy materials are in the inventory, then:

```bat
python enchanter.py check            # verifies OCR region and every template
python enchanter.py sim --seed 1     # dry run with a simulated game, no input sent
python enchanter.py run --once       # one real attempt
python enchanter.py run              # full queue
```

Hotkeys while running: `F9` stop, `F10` pause/resume. Moving the mouse into
a screen corner also aborts (pyautogui fail-safe). Logs show every decision.

## Layout

| File | Purpose |
| --- | --- |
| `enchanter.py` | CLI, screen capture / OCR / clicking, control loop, simulator |
| `planner.py` | Pure decision logic (which item, which stage, how many stones) |
| `config.example.yaml` | Annotated configuration template |
| `tests/test_planner.py` | Unit tests: `python -m pytest` |

## Limitations

- Only `BASE -> PRI -> DUO` on yellow accessories. Higher stages, Valks
  stacks, Cron Stones and failstack storage are intentionally out of scope.
- Result detection relies on the failstack counter (0 = success, higher =
  fail); it does not read the success/fail popup.
- Any UI-scale, resolution or patch change means re-cropping the templates.
