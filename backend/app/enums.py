"""跨模块共享的枚举。"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """任务状态机中的状态。"""

    PENDING = "PENDING"
    IDENTIFYING = "IDENTIFYING"
    # 人工检查点 1：确认 / 编辑材质卡片
    AWAIT_MATERIAL_CONFIRM = "AWAIT_MATERIAL_CONFIRM"
    MATERIAL_SEARCH = "MATERIAL_SEARCH"
    # 人工检查点 2（可选）：挑选 / 更换材质图
    AWAIT_MATERIAL_SELECT = "AWAIT_MATERIAL_SELECT"
    # 人工检查点 3：填写设计想法后触发生成
    AWAIT_DESIGN_IDEA = "AWAIT_DESIGN_IDEA"
    GENERATING = "GENERATING"
    DONE = "DONE"
    FAILED = "FAILED"


# 处于等待用户输入（人工检查点）的状态集合
WAITING_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.AWAIT_MATERIAL_CONFIRM,
        TaskStatus.AWAIT_MATERIAL_SELECT,
        TaskStatus.AWAIT_DESIGN_IDEA,
    }
)

# 终态
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.DONE, TaskStatus.FAILED}
)


class MaterialSource(StrEnum):
    """材质卡片的来源：AI 识别 or 用户人工确认过的编辑结果。"""

    AI = "ai"
    USER = "user"


class MaterialImageOrigin(StrEnum):
    """面料参考图来源：按卡片检索得到 or 用户在任务详情页上传。"""

    SEARCH = "search"
    UPLOAD = "upload"
