from enum import Enum

from ..graph import BaseInput
from ..model.agent import AgentResult
from ..model.input import UserInput
from ..model.workflow import WorkflowTask


class TurnStatus(str, Enum):
    """轮次状态"""
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentTurn:
    """
    单轮交互

    参数:
        input: 本轮用户输入
        result: 本轮运行结果
    """
    def __init__(self, input: UserInput | type[BaseInput], result: AgentResult):
        self._input = input
        self._result = result
        self._status = TurnStatus.RUNNING
        self._workflow_tasks: dict[str, WorkflowTask] = {}

        self._pre_checkpoint_id: str | None = None
        self._latest_checkpoint_id: str | None = None
        self._error: str | None = None

    @property
    def input(self) -> UserInput | type[BaseInput]:
        return self._input

    @property
    def result(self) -> AgentResult:
        return self._result

    @result.setter
    def result(self, value: AgentResult) -> None:
        self._result = value

    @property
    def status(self) -> TurnStatus:
        return self._status

    @status.setter
    def status(self, value: TurnStatus) -> None:
        self._status = value

    @property
    def workflow_tasks(self) -> dict[str, WorkflowTask]:
        return self._workflow_tasks

    @property
    def tool_names(self) -> list[str]:
        return list(self._result.tool_names)

    @property
    def pre_checkpoint_id(self) -> str | None:
        return self._pre_checkpoint_id

    @pre_checkpoint_id.setter
    def pre_checkpoint_id(self, value: str | None) -> None:
        self._pre_checkpoint_id = value

    @property
    def latest_checkpoint_id(self) -> str | None:
        return self._latest_checkpoint_id

    @latest_checkpoint_id.setter
    def latest_checkpoint_id(self, value: str | None) -> None:
        self._latest_checkpoint_id = value

    @property
    def error(self) -> str | None:
        return self._error

    @error.setter
    def error(self, value: str | None) -> None:
        self._error = value
