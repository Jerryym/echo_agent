from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CaseInfo:
    """
    测试用例信息
    """
    name: str
    title: str
    handler: Any = None


class CaseRegistry:
    """
    Case Registry：测试用例注册
    """

    def __init__(self):
        self._cases: dict[str, CaseInfo] = {}

    def register(self, case: CaseInfo) -> None:
        self._cases[case.name] = case

    def unregister(self, name: str) -> None:
        self._cases.pop(name, None)

    def get(self, name: str) -> CaseInfo:
        return self._cases[name]

    def list_cases(self) -> list[CaseInfo]:
        return list(self._cases.values())

    def list_titles(self) -> list[str]:
        return [case.title for case in self._cases.values()]
