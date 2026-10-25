# bdo-enchanter

Auto-enhancer for Black Desert Online accessories (built for Deboreka) on
**Linux / X11**. It navigates the game's menus itself, consumes Black Stones
until the failstack matches the attempt, puts an accessory in the enhancement
slot, presses Enhance and reads the result.

Two phases, each one command:

- `./enchanter pri` - enhance base copies until each accessory type has the
  number of **PRI** copies you asked for (15 failstacks per attempt).
- `./enchanter duo` - when you are ready, enhance **every PRI copy to DUO**
  (40 failstacks per attempt).

> **Warning.** This is a screen-reading macro (picture matching + OCR +
> synthetic input). Third-party automation violates Pearl Abyss' Terms of
> Service and can get an account banned. Use at your own risk and never leave
> it unattended. Accessories are destroyed on failure; a bad picture could make
> it click the wrong item.

## Install

Debian/Ubuntu-based distro, X11 session (not Wayland), game in Windowed or
Borderless mode.

```bash
git clone <this repo> && cd bdo-enchanter
./install.sh          # apt: python3-tk tesseract-ocr xdotool ...; creates .venv
./enchanter setup     # guided setup, see below
```

## Setup: the wizard learns your UI

`./enchanter setup` never asks for coordinates. It learns two kinds of things:

**Menu paths, by recording.** For each path it asks you step by step: press a
key, click something, wait, or done. For a click you drag a box around the
button on a frozen screenshot. The wizard performs every step right after you
describe it, so the game moves along with the recording. Paths recorded:

| flow | from -> to |
| --- | --- |
| `open_enhancement` | normal view -> enhancement window with inventory (e.g. `,` then click Enhancement, then `i`) |
| `open_failstack_menu` | enhancement window -> where Black Stones are consumed (empty if it is the same window) |
| `add_failstack` | consume one Black Stone for +1 failstack (one stone really is used, and the counter is checked) |
| `close_failstack_menu` | back to the enhancement window |
| `enhance` | the Enhance button (+ optional confirm); *not* performed during setup |

**Pictures and regions, by drawing boxes.** A fixed part of the enhancement
window (so the bot knows it is open), the failstack number (OCR'd on the spot
and confirmed with you), the inventory grid (items are only searched and
clicked inside it, so the item already in the slot is never touched), and the
icon of each accessory type. PRI and DUO icons are captured automatically
the first time one appears after a success; the bot pauses and asks.

The wizard ends with a click test (left vs right click to move an item into
the slot) and a verification pass, then writes `config.yaml` and `templates/`.

## Running

```bash
./enchanter check               # read the screen, count items, click nothing
./enchanter pri --attempts 1    # one real attempt, watch it
./enchanter pri                 # until each type has its PRI goal
./enchanter pri --count 3       # override the goal for every type
./enchanter duo                 # every PRI copy -> DUO
```

`F9` stops, `F10` pauses, moving the mouse into a screen corner aborts.

Each attempt: make sure the enhancement window is open (replay the recorded
path if not) -> read the failstack -> if short, open the failstack menu and
consume stones one at a time, verifying the counter -> close it -> click the
right accessory in the inventory -> Enhance -> read the counter (0 = success,
higher = fail).

The bot stops with a message when:

- the PRI goal is reached / no PRI copies remain (phase done),
- there are not enough base copies (an attempt needs the item plus a base copy
  as material),
- the current stack is more than `failstack.max_overshoot` above what the next
  attempt needs (so it does not waste a big stack),
- the counter stops moving after stones (out of Black Stones or cap reached),
- the counter does not change after Enhance (no material, wrong item),
- any recorded picture is no longer found.

## Layout

| path | purpose |
| --- | --- |
| `enchanter` | launcher (`.venv/bin/python -m bdo_enchanter`) |
| `install.sh` | apt packages + virtualenv |
| `bdo_enchanter/wizard.py` | guided setup, flow recorder, runtime icon capture |
| `bdo_enchanter/picker.py` | drag-a-box region picker over a screenshot |
| `bdo_enchanter/screen.py` | capture, picture matching (single/multi), OCR, clicks, keys, window focus |
| `bdo_enchanter/game.py` | plays recorded flows; failstack raising; inventory counting; enhance + result |
| `bdo_enchanter/phases.py` | PRI/DUO phase logic (game-agnostic, unit-tested) |
| `config.example.yaml` | annotated example of the generated configuration |
| `tests/` | `python -m pytest` |

## Limitations

- BASE -> PRI -> DUO only. Cron Stones, Valks stacks and failstack storage are out of scope.
- Keep the accessories and materials visible in the inventory box you drew (no scrolling).
- Any resolution, UI-scale or patch change: re-run `./enchanter setup`.
- The game must be on the primary monitor.
