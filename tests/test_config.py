import yaml

from enchanter import item_locator, load_config, save_config
from planner import Stage


def test_item_locator_per_stage_and_single():
    entry = {"name": "r", "current": "BASE", "templates": {"BASE": "a.png", "PRI": "b.png"}}
    assert item_locator(entry, Stage.BASE) == "a.png"
    assert item_locator(entry, Stage.PRI) == "b.png"
    assert item_locator(entry, Stage.DUO) is None

    single = {"name": "r", "current": "PRI", "template": "c.png"}
    assert item_locator(single, Stage.PRI) == {"template": "c.png"}
    assert item_locator(single, Stage.BASE) is None


def test_runtime_edits_to_items_persist_through_save(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "failstack": {"region": [1, 2, 3, 4]},
        "items": [{"name": "Ring", "current": "BASE", "target": "DUO", "templates": {"BASE": "x.png"}}],
    }))
    cfg = load_config(path)
    assert cfg["targets"] == {Stage.PRI: 15, Stage.DUO: 40}
    assert cfg["failstack"]["max_overshoot"] == 3  # default merged in

    # The game layer mutates the entry dict when it captures a new picture.
    cfg["items"][0]["templates"]["PRI"] = "y.png"
    save_config(cfg["_path"], cfg["_raw"])

    reloaded = yaml.safe_load(path.read_text())
    assert reloaded["items"][0]["templates"] == {"BASE": "x.png", "PRI": "y.png"}
    assert not any(k.startswith("_") for k in reloaded)
