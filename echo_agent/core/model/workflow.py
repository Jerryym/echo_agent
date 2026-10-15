from copy import deepcopy
import json
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr


# 工作流任务状态
WorkflowTaskStatus = Literal[
    "active",
    "completed",
    "failed",
]


class WorkflowTask(BaseModel):
    """
    工作流任务

    参数:
        task_id: 工作流任务唯一标识
        status: 任务生命周期状态
        state: 工作流任务状态
    """
    task_id: str = Field(
        description="Unique identifier of the workflow task."
    )
    _status: WorkflowTaskStatus = PrivateAttr(default="active")
    _state: dict[str, Any] = PrivateAttr(default_factory=dict)
    _lock: RLock = PrivateAttr(default_factory=RLock)

    @property
    def status(self) -> WorkflowTaskStatus:
        with self._lock:
            return self._status

    @property
    def state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def update(self, state: BaseModel) -> None:
        """更新"""
        data = self._serialize_state(state)
        with self._lock:
            self._ensure_active()
            self._state = data

    def finish(self) -> None:
        """标记任务完成"""
        with self._lock:
            self._ensure_active()
            self._status = "completed"

    def fail(self) -> None:
        """标记任务失败"""
        with self._lock:
            self._ensure_active()
            self._status = "failed"

    def _ensure_active(self) -> None:
        if self.status != "active":
            raise RuntimeError(
                f"Workflow task is not active: "
                f"{self.task_id} (status={self.status})"
            )

    @staticmethod
    def _serialize_state(state: BaseModel) -> dict[str, Any]:
        data = state.model_dump(mode="json")
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
        )
        return deepcopy(data)
