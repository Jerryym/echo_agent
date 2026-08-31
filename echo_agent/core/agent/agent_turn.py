from ..model.input import UserInput
from ..model.agent import AgentResult
from ..graph import BaseInput


class AgentTurn:
    def __init__(self, input: UserInput | type[BaseInput], result: AgentResult):
        self._input = input
        self._result = result

    @property
    def input(self) -> UserInput | type[BaseInput]:
        return self._input

    @property
    def result(self) -> AgentResult:
        return self._result