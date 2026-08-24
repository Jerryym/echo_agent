from typing import Any

from ...runtime.gateway import BaseGateWay


class SkillGateWay(BaseGateWay):
    """
    Skill网关：用于管理运行时Skill的有效性
    """
    def authorize(self, target: Any, **kwargs: Any) -> None:
        """授权检查"""
        pass
