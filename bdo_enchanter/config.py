"""Configuration loading, defaults and persistence."""
from __future__ import annotations

from enum import IntEnum
from pathlib import Path

import yaml


class Stage(IntEnum):
    BASE = 0
    PRI = 1
    DUO = 2

    @property
    def next(self) -> "Stage":
        return Stage(self + 1)

    @classmethod
    def parse(cls, value) -> "Stage":
        try:
            return cls(value) if isinstance(value, int) else cls[str(value).strip().upper()]
        except (KeyError, ValueError):
            raise ValueError(f"unknown stage {value!r}") from None


# Failstacks the game adds when an accessory attempt at a stage fails.
FAIL_GAIN = {Stage.PRI: 1, Stage.DUO: 2}

FLOW_NAMES = (
    "open_enhancement",      # normal game view -> enhancement window + inventory visible
    "open_failstack_menu",   # enhancement window -> wherever Black Stones are consumed (may be empty)
    "add_failstack",         # consume one Black Stone (+1 failstack)
    "close_failstack_menu",  # back to the enhancement window (may be empty)
    "enhance",               # press Enhance (+ confirm if the UI asks)
)

DEFAULTS: dict = {
    "targets": {"PRI": 15, "DUO": 40},
    "failstack": {"max_overshoot": 3},
    "delays": {
        "after_click": 0.4,
        "after_key": 0.8,
        "after_failstack": 0.5,
        "after_enhance": 3.0,
        "result_timeout": 10.0,
    },
    "match_threshold": 0.85,
    "select_click": "left",
    "game_window": "Black Desert",
    "hotkeys": {"stop": "f9", "pause": "f10"},
    "flows": {name: [] for name in FLOW_NAMES},
    "items": [],
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Merged view over defaults + the YAML file, remembering where it lives."""

    def __init__(self, path: Path, raw: dict | None = None) -> None:
        self.path = Path(path).resolve()
        self.dir = self.path.parent
        self.raw: dict = raw if raw is not None else {}
        self.data: dict = deep_merge(DEFAULTS, self.raw)

    @classmethod
    def load(cls, path: Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise SystemExit(f"{path} not found. Run:  ./enchanter setup")
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls(path, raw)

    def save(self) -> None:
        self.data = deep_merge(DEFAULTS, self.raw)
        with open(self.path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.raw, fh, sort_keys=False, allow_unicode=True)

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    # -- convenience --------------------------------------------------------
    def target_fs(self, stage: Stage) -> int:
        return int(self.data["targets"][stage.name])

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.dir / p

    def template_dir(self) -> Path:
        d = self.dir / "templates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def item_template(self, item: dict, stage: Stage) -> str | None:
        return (item.get("templates") or {}).get(stage.name)
