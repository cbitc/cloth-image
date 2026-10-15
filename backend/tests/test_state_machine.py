"""状态机测试。"""

from __future__ import annotations

import pytest

from app.enums import TaskStatus
from app.tasks.state_machine import (
    InvalidTransition,
    assert_transition,
    can_transition,
    next_after_material_search,
)


def test_happy_path_transitions() -> None:
    path = [
        TaskStatus.PENDING,
        TaskStatus.IDENTIFYING,
        TaskStatus.AWAIT_MATERIAL_CONFIRM,
        TaskStatus.MATERIAL_SEARCH,
        TaskStatus.AWAIT_DESIGN_IDEA,
        TaskStatus.GENERATING,
        TaskStatus.DONE,
    ]
    for current, target in zip(path, path[1:]):
        assert can_transition(current, target), f"{current} -> {target}"


def test_invalid_transition_raises() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(TaskStatus.PENDING, TaskStatus.DONE)


def test_failed_recovery() -> None:
    assert can_transition(TaskStatus.FAILED, TaskStatus.PENDING)
    assert can_transition(TaskStatus.GENERATING, TaskStatus.FAILED)


def test_next_after_material_search() -> None:
    assert (
        next_after_material_search(
            require_selection=True, auto_generate=True, has_idea=True
        )
        == TaskStatus.AWAIT_MATERIAL_SELECT
    )
    assert (
        next_after_material_search(
            require_selection=False, auto_generate=True, has_idea=True
        )
        == TaskStatus.GENERATING
    )
    assert (
        next_after_material_search(
            require_selection=False, auto_generate=False, has_idea=True
        )
        == TaskStatus.AWAIT_DESIGN_IDEA
    )


def test_regenerate_allowed_from_done() -> None:
    assert can_transition(TaskStatus.DONE, TaskStatus.GENERATING)
    assert can_transition(TaskStatus.AWAIT_DESIGN_IDEA, TaskStatus.MATERIAL_SEARCH)


def test_research_materials_allowed_after_done() -> None:
    """已完成的任务仍可改检索条件重跑面料检索（回到编辑链）。"""
    assert can_transition(TaskStatus.DONE, TaskStatus.MATERIAL_SEARCH)
    assert can_transition(TaskStatus.AWAIT_MATERIAL_SELECT, TaskStatus.MATERIAL_SEARCH)


def test_research_materials_rejected_while_busy() -> None:
    for busy in (
        TaskStatus.IDENTIFYING,
        TaskStatus.MATERIAL_SEARCH,
        TaskStatus.GENERATING,
    ):
        assert not can_transition(busy, TaskStatus.MATERIAL_SEARCH)
