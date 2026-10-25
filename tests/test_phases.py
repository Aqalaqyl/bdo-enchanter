from pathlib import Path

import pytest

from bdo_enchanter.config import FAIL_GAIN, Config, Stage
from bdo_enchanter.phases import Controls, GameError, Halt, run_phase


class FakeGame:
    """Inventory + failstack model driven by a scripted list of outcomes."""

    def __init__(self, inventory: dict[Stage, int], outcomes: list[bool], fs: int = 0, stones: int = 1000):
        self.inv = dict(inventory)
        self.outcomes = list(outcomes)
        self.fs = fs
        self.stones = stones
        self.slot: Stage | None = None
        self.opened = 0
        self.captured: list[Stage] = []
        self.log: list[str] = []

    def ensure_enhancement_open(self):
        self.opened += 1

    def read_failstack(self):
        return self.fs

    def raise_failstack_to(self, target):
        while self.fs < target and self.stones > 0:
            self.stones -= 1
            self.fs += 1
        return self.fs

    def count_items(self, item):
        return {s: self.inv.get(s, 0) for s in Stage}

    def place_item(self, item, stage):
        if self.inv.get(stage, 0) == 0:
            return False
        self.slot = stage
        return True

    def enhance_and_wait(self, fs_before, stage):
        assert self.slot == Stage(stage - 1), "wrong item in the slot"
        self.log.append(f"{stage.name}@{fs_before}")
        ok = self.outcomes.pop(0)
        self.inv[self.slot] -= 1          # the item itself
        self.inv[Stage.BASE] -= 1         # the material
        if ok:
            self.inv[stage] = self.inv.get(stage, 0) + 1
            self.fs = 0
        else:
            self.fs += FAIL_GAIN[stage]
        self.slot = None
        return ok

    def ensure_template(self, item, stage):
        self.captured.append(stage)


def cfg(**over):
    raw = {"items": [{"name": "Deboreka Ring", "pri_count": 2, "templates": {"BASE": "b.png"}}]}
    raw.update(over)
    return Config(Path("/tmp/does-not-exist.yaml"), raw)


def test_pri_phase_stops_at_goal_and_uses_15_fs():
    c = cfg()
    g = FakeGame({Stage.BASE: 10}, outcomes=[True, False, True])
    stats = run_phase(g, c["items"], Stage.PRI, c, Controls())
    # success resets to 0 so the next attempt rebuilds 15; a fail leaves 16, reused (within overshoot)
    assert g.log == ["PRI@15", "PRI@15", "PRI@16"]
    assert g.inv[Stage.PRI] == 2
    assert (stats.attempts, stats.success, stats.fail) == (3, 2, 1)
    assert g.captured == [Stage.PRI, Stage.PRI]
    assert "2 PRI reached" in stats.notes[0]


def test_pri_phase_needs_two_base_copies():
    c = cfg()
    g = FakeGame({Stage.BASE: 1}, outcomes=[])
    stats = run_phase(g, c["items"], Stage.PRI, c, Controls())
    assert stats.attempts == 0
    assert "need 2 BASE" in stats.notes[0]


def test_duo_phase_runs_until_no_pri_left_at_40_fs():
    c = cfg()
    g = FakeGame({Stage.BASE: 5, Stage.PRI: 2}, outcomes=[False, True])
    stats = run_phase(g, c["items"], Stage.DUO, c, Controls())
    assert g.log == ["DUO@40", "DUO@42"]  # +2 on a DUO fail, 42 is within overshoot of 40
    assert g.inv[Stage.PRI] == 0 and g.inv[Stage.DUO] == 1
    assert "no PRI copies left" in stats.notes[0]


def test_duo_phase_needs_base_material():
    c = cfg()
    g = FakeGame({Stage.BASE: 0, Stage.PRI: 2}, outcomes=[])
    stats = run_phase(g, c["items"], Stage.DUO, c, Controls())
    assert stats.attempts == 0 and "material" in stats.notes[0]


def test_large_overshoot_halts_instead_of_wasting_stack():
    c = cfg()
    g = FakeGame({Stage.BASE: 10}, outcomes=[True], fs=30)
    with pytest.raises(Halt):
        run_phase(g, c["items"], Stage.PRI, c, Controls())


def test_out_of_stones_is_an_error():
    c = cfg()
    g = FakeGame({Stage.BASE: 10}, outcomes=[True], stones=5)
    with pytest.raises(GameError):
        run_phase(g, c["items"], Stage.PRI, c, Controls())


def test_max_attempts_and_count_override():
    c = cfg()
    c["items"][0]["pri_count"] = 5
    g = FakeGame({Stage.BASE: 20}, outcomes=[True, True, True])
    stats = run_phase(g, c["items"], Stage.PRI, c, Controls(), max_attempts=1)
    assert stats.attempts == 1
    assert "stopped after 1" in stats.notes[-1]


def test_config_defaults_and_save_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    c = Config(path, {"items": [{"name": "x", "templates": {}}], "targets": {"PRI": 20}})
    assert c.target_fs(Stage.PRI) == 20 and c.target_fs(Stage.DUO) == 40
    c["items"][0]["templates"]["PRI"] = "p.png"  # runtime capture mutates the shared entry
    c.save()
    again = Config.load(path)
    assert again["items"][0]["templates"] == {"PRI": "p.png"}
    assert again["flows"]["enhance"] == []
