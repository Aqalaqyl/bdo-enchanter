import pytest

from planner import Done, Halt, Item, Plan, Stage, apply_result, choose_next, expand_items

TARGETS = {Stage.PRI: 15, Stage.DUO: 40}


def item(name="ring", stage=Stage.BASE, target=Stage.DUO):
    return Item(name=name, stage=stage, target=target, locator={})


def test_builds_stack_to_pri_from_zero():
    plan = choose_next([item()], 0, TARGETS, 3)
    assert isinstance(plan, Plan)
    assert plan.stage == Stage.PRI
    assert plan.required_fs == 15
    assert plan.stones_to_add == 15


def test_after_pri_success_builds_to_duo():
    items = [item()]
    apply_result(items, items[0], success=True)
    plan = choose_next(items, 0, TARGETS, 3)
    assert plan.stage == Stage.DUO
    assert plan.required_fs == 40
    assert plan.stones_to_add == 40


def test_fail_destroys_item():
    items = [item(), item("second")]
    apply_result(items, items[0], success=False)
    assert [i.name for i in items] == ["second"]


def test_done_when_everything_reached_target():
    items = [item(stage=Stage.PRI, target=Stage.PRI)]
    assert isinstance(choose_next(items, 0, TARGETS, 3), Done)


def test_prefers_highest_fitting_requirement():
    """With a 41 stack, do the DUO attempt, not the PRI one."""
    items = [item("pri-only", target=Stage.PRI), item("duo", stage=Stage.PRI)]
    plan = choose_next(items, 41, TARGETS, 3)
    assert plan.item.name == "duo"
    assert plan.stones_to_add == 0


def test_small_overshoot_is_used():
    plan = choose_next([item(target=Stage.PRI)], 16, TARGETS, 3)
    assert isinstance(plan, Plan)
    assert plan.stones_to_add == 0


def test_large_overshoot_halts():
    """A 42 stack after a DUO fail must not be burnt on a PRI."""
    decision = choose_next([item(target=Stage.PRI)], 42, TARGETS, 3)
    assert isinstance(decision, Halt)


def test_when_nothing_fits_pick_lowest_requirement():
    items = [item("duo", stage=Stage.PRI), item("pri", target=Stage.PRI)]
    plan = choose_next(items, 10, TARGETS, 3)
    assert plan.item.name == "pri"
    assert plan.stones_to_add == 5


def test_expand_items_count_and_validation():
    items = expand_items([{"name": "ring", "current": "base", "target": "duo", "count": 3}])
    assert len(items) == 3
    assert all(i.stage == Stage.BASE and i.target == Stage.DUO for i in items)

    with pytest.raises(ValueError):
        expand_items([{"name": "x", "current": "PRI", "target": "PRI"}])
    with pytest.raises(ValueError):
        expand_items([{"name": "x", "current": "DUO", "target": "TRI"}])
