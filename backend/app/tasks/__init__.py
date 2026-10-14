"""任务编排包。

为避免循环导入，此处只导出轻量对象；
orchestrator / persist / serialize 请按需显式导入（如 `from app.tasks import orchestrator`）。
"""

from app.tasks.dispatcher import (
    InlineDispatcher,
    SyncDispatcher,
    get_dispatcher,
)
from app.tasks.state_machine import (
    InvalidTransition,
    assert_transition,
    can_transition,
    is_terminal,
    is_waiting,
)

__all__ = [
    "InlineDispatcher",
    "SyncDispatcher",
    "get_dispatcher",
    "InvalidTransition",
    "assert_transition",
    "can_transition",
    "is_terminal",
    "is_waiting",
]
