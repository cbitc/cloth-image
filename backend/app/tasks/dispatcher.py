"""任务分发：把「执行某任务第一阶段」这件事交给不同执行器。

sync    —— 同步执行（测试）
inline  —— 线程池后台执行（响应立即返回，默认）
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        # SQLite 并发写入易锁 → 单线程串行执行
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="task")
    return _executor


class Dispatcher(Protocol):
    def dispatch_identify(self, task_id: str) -> None: ...

    def dispatch_material_search(self, task_id: str) -> None: ...

    def dispatch_generate(
        self,
        task_id: str,
        design_idea: str | None = None,
        num_candidates: int | None = None,
    ) -> None: ...


class SyncDispatcher:
    """当前线程直接执行，便于测试。"""

    def dispatch_identify(self, task_id: str) -> None:
        from app.tasks import orchestrator

        orchestrator.run_identify(task_id)

    def dispatch_material_search(self, task_id: str) -> None:
        from app.tasks import orchestrator

        orchestrator.run_material_search(task_id)

    def dispatch_generate(
        self,
        task_id: str,
        design_idea: str | None = None,
        num_candidates: int | None = None,
    ) -> None:
        from app.tasks import orchestrator

        orchestrator.run_generate(task_id, design_idea, num_candidates)


class InlineDispatcher:
    """线程池后台执行，HTTP 响应不被阻塞。"""

    def _submit(self, fn, *args) -> None:
        _get_executor().submit(fn, *args)

    def dispatch_identify(self, task_id: str) -> None:
        from app.tasks import orchestrator

        self._submit(orchestrator.run_identify, task_id)

    def dispatch_material_search(self, task_id: str) -> None:
        from app.tasks import orchestrator

        self._submit(orchestrator.run_material_search, task_id)

    def dispatch_generate(
        self,
        task_id: str,
        design_idea: str | None = None,
        num_candidates: int | None = None,
    ) -> None:
        from app.tasks import orchestrator

        self._submit(orchestrator.run_generate, task_id, design_idea, num_candidates)


def get_dispatcher() -> Dispatcher:
    mode = (get_settings().task_execution or "inline").lower()
    if mode == "sync":
        return SyncDispatcher()
    return InlineDispatcher()
