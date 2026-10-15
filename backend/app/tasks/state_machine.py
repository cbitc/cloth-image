"""任务状态机：定义合法状态转移并做守卫。

  PENDING ─▶ IDENTIFYING ─▶ AWAIT_MATERIAL_CONFIRM ─▶ MATERIAL_SEARCH
      ─▶ [AWAIT_MATERIAL_SELECT] ─▶ AWAIT_DESIGN_IDEA ─▶ GENERATING ─▶ DONE
  任意阶段失败 ─▶ FAILED（可 retry 回 PENDING）

到 DONE 之后仍可回到编辑链：改设计想法再生成（DONE → GENERATING），
或改检索条件后重跑面料检索（DONE → MATERIAL_SEARCH）。

方括号为可选检查点：require_material_selection=True 才停留在 AWAIT_MATERIAL_SELECT；
auto_generate=True 且已有设计想法时跳过 AWAIT_DESIGN_IDEA。
"""

from __future__ import annotations

from app.enums import TERMINAL_STATUSES, WAITING_STATUSES, TaskStatus

TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.IDENTIFYING, TaskStatus.FAILED},
    TaskStatus.IDENTIFYING: {TaskStatus.AWAIT_MATERIAL_CONFIRM, TaskStatus.FAILED},
    TaskStatus.AWAIT_MATERIAL_CONFIRM: {TaskStatus.MATERIAL_SEARCH, TaskStatus.FAILED},
    TaskStatus.MATERIAL_SEARCH: {
        TaskStatus.AWAIT_MATERIAL_SELECT,
        TaskStatus.AWAIT_DESIGN_IDEA,
        TaskStatus.GENERATING,
        TaskStatus.FAILED,
    },
    TaskStatus.AWAIT_MATERIAL_SELECT: {
        TaskStatus.MATERIAL_SEARCH,
        TaskStatus.AWAIT_DESIGN_IDEA,
        TaskStatus.GENERATING,
        TaskStatus.FAILED,
    },
    TaskStatus.AWAIT_DESIGN_IDEA: {
        TaskStatus.MATERIAL_SEARCH,
        TaskStatus.GENERATING,
        TaskStatus.FAILED,
    },
    TaskStatus.GENERATING: {TaskStatus.DONE, TaskStatus.FAILED},
    # DONE 允许再生成（「换一版」）；也允许改检索条件后重跑面料检索（回到编辑链）
    TaskStatus.DONE: {TaskStatus.GENERATING, TaskStatus.MATERIAL_SEARCH},
    TaskStatus.FAILED: {TaskStatus.PENDING},
}

# 各阶段用于 UI 展示的进度
STAGE_PROGRESS: dict[TaskStatus, float] = {
    TaskStatus.PENDING: 0.0,
    TaskStatus.IDENTIFYING: 0.15,
    TaskStatus.AWAIT_MATERIAL_CONFIRM: 0.3,
    TaskStatus.MATERIAL_SEARCH: 0.45,
    TaskStatus.AWAIT_MATERIAL_SELECT: 0.6,
    TaskStatus.AWAIT_DESIGN_IDEA: 0.7,
    TaskStatus.GENERATING: 0.85,
    TaskStatus.DONE: 1.0,
    TaskStatus.FAILED: 1.0,
}


class InvalidTransition(RuntimeError):
    def __init__(self, current: TaskStatus | str, target: TaskStatus | str) -> None:
        super().__init__(f"非法状态转移: {current} -> {target}")
        self.current = TaskStatus(current)
        self.target = TaskStatus(target)


def can_transition(current: TaskStatus | str, target: TaskStatus | str) -> bool:
    current = TaskStatus(current)
    target = TaskStatus(target)
    return target in TRANSITIONS.get(current, set())


def assert_transition(current: TaskStatus | str, target: TaskStatus | str) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)


def is_waiting(status: TaskStatus | str) -> bool:
    return TaskStatus(status) in WAITING_STATUSES


def is_terminal(status: TaskStatus | str) -> bool:
    return TaskStatus(status) in TERMINAL_STATUSES


def next_after_material_search(
    *, require_selection: bool, auto_generate: bool, has_idea: bool
) -> TaskStatus:
    """材质检索完成后应进入的状态。"""
    if require_selection:
        return TaskStatus.AWAIT_MATERIAL_SELECT
    if auto_generate and has_idea:
        return TaskStatus.GENERATING
    return TaskStatus.AWAIT_DESIGN_IDEA
