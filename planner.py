"""Pure decision logic for the enhancer.

Nothing in here touches the screen, so it can be tested without the game.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping, Sequence


class Stage(IntEnum):
    BASE = 0
    PRI = 1
    DUO = 2

    @classmethod
    def parse(cls, value: str | int) -> "Stage":
        try:
            if isinstance(value, int):
                return cls(value)
            return cls[str(value).strip().upper()]
        except (KeyError, ValueError):
            raise ValueError(f"unknown stage {value!r}; expected one of {[s.name for s in cls]}") from None


# Failstacks gained when an accessory enhancement at the given stage fails.
# Only used as a fallback when the failstack counter cannot be read.
FAIL_GAIN = {Stage.PRI: 1, Stage.DUO: 2}


@dataclass
class Item:
    """One physical accessory in the inventory."""

    name: str
    stage: Stage
    target: Stage
    # Per-stage overrides for how to find the item on screen (template path or
    # slot coordinates). Interpreted by the game layer, opaque here.
    locator: Mapping = None

    @property
    def next_stage(self) -> Stage:
        return Stage(self.stage + 1)

    @property
    def done(self) -> bool:
        return self.stage >= self.target


@dataclass
class Plan:
    item: Item
    stage: Stage  # stage being attempted
    required_fs: int
    stones_to_add: int  # failstacks that must still be built with black stones


@dataclass
class Halt:
    reason: str


class Done:
    pass


Decision = Plan | Halt | Done


def expand_items(entries: Sequence[Mapping]) -> list[Item]:
    """Turn config entries (with an optional ``count``) into individual items."""
    items: list[Item] = []
    for entry in entries:
        stage = Stage.parse(entry.get("current", "BASE"))
        target = Stage.parse(entry.get("target", "PRI"))
        if target <= stage:
            raise ValueError(f"{entry.get('name')}: target {target.name} is not above current {stage.name}")
        if target > Stage.DUO:
            raise ValueError(f"{entry.get('name')}: only PRI and DUO targets are supported")
        count = int(entry.get("count", 1))
        for _ in range(count):
            items.append(Item(name=entry["name"], stage=stage, target=target, locator=entry))
    return items


def choose_next(
    items: Sequence[Item],
    current_fs: int,
    targets: Mapping[Stage, int],
    max_overshoot: int,
) -> Decision:
    """Pick the attempt that makes the best use of the current failstack.

    Preference order:
      1. Among attempts whose required failstack is already met, the one with the
         highest requirement (don't burn a 40 stack on a PRI).
      2. Otherwise the attempt with the lowest requirement, building the
         difference with black stones.

    If the stack is already higher than every usable attempt by more than
    ``max_overshoot``, halt so a human can decide what to do with the stack.
    """
    pending = [i for i in items if not i.done]
    if not pending:
        return Done()

    candidates = [(targets[i.next_stage], i) for i in pending]
    fitting = [c for c in candidates if c[0] <= current_fs]

    if fitting:
        required, item = max(fitting, key=lambda c: c[0])
        if current_fs - required > max_overshoot:
            return Halt(
                f"failstack {current_fs} exceeds the {required} needed for "
                f"{item.name} {item.next_stage.name} by more than {max_overshoot}; "
                "store or use the stack manually"
            )
        return Plan(item=item, stage=item.next_stage, required_fs=required, stones_to_add=0)

    required, item = min(candidates, key=lambda c: c[0])
    return Plan(item=item, stage=item.next_stage, required_fs=required, stones_to_add=required - current_fs)


def apply_result(items: list[Item], item: Item, success: bool) -> None:
    """Update the item list after an attempt.

    Yellow accessories are destroyed on failure, so a failed item is removed.
    """
    if success:
        item.stage = item.next_stage
    else:
        items.remove(item)
