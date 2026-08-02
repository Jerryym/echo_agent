from typing import Any

from ...graph.schema import BaseContext
from ...model.skill import SkillPackage, SkillRuntimeContext, SkillStatus
from .skill_loader import SkillLoader
from .skill_parser import SkillParser


class SkillManager:
    """
    Skill Manager：Skill管理器, 负责管理Skill的生命周期

    状态机：UNLOADED → LOADED → DISCARDED
    - load：激活为 LOADED，并重置 idle_rounds
    - touch：标记本轮被使用（idle_rounds = 0）
    - discard / unload：标为 DISCARDED 并从 active_skills 移除
    - expire_idle：每个 Reason 轮对 LOADED 技能 idle+1，达 3 轮则 discard
    """
    DEFAULT_MAX_IDLE_ROUNDS = 3

    def __init__(self, skill_list: dict[str, Any]):
        self._skill_list = skill_list

    def get_skill(self, context: BaseContext, skill_name: str) -> SkillRuntimeContext | None:
        """
        获取Skill
        """
        return context.active_skills.get(skill_name)

    def has_skill(self, context: BaseContext, skill_name: str) -> bool:
        """
        判断Skill是否已加载
        """
        skill = context.active_skills.get(skill_name)
        return skill is not None and skill.status == SkillStatus.LOADED

    def build_skill_package(self, skill_name: str) -> SkillPackage:
        """
        根据skill name构建 SkillPackage。
        """
        skill_dir = self._skill_list.get(skill_name)
        if skill_dir is None:
            raise ValueError(f"Skill not found: {skill_name}")
        return SkillParser.parse(skill_dir)

    def load_skill(self, context: BaseContext, skill_package: SkillPackage) -> SkillRuntimeContext:
        """
        加载Skill（激活为 LOADED，并重置 idle）。
        """
        skill_name = skill_package.frontmatter.name
        if not skill_name:
            raise ValueError("Skill name is required")

        existing = context.active_skills.get(skill_name)
        if existing is not None and existing.status == SkillStatus.LOADED:
            existing.idle_rounds = 0
            return existing

        skill_context = SkillLoader.load(skill_package)
        skill_context.idle_rounds = 0
        context.active_skills[skill_name] = skill_context
        return skill_context

    def touch_skill(self, context: BaseContext, skill_name: str) -> None:
        """标记 Skill 本轮被使用，重置 idle_rounds。"""
        skill = context.active_skills.get(skill_name)
        if skill is None or skill.status != SkillStatus.LOADED:
            return
        skill.idle_rounds = 0

    def discard_skill(self, context: BaseContext, skill_name: str) -> None:
        """
        废弃 Skill：status → DISCARDED，清空 instruction，移出 active_skills。
        """
        skill = context.active_skills.pop(skill_name, None)
        if skill is None:
            return
        skill.status = SkillStatus.DISCARDED
        skill.instruction = None

    def unload_skill(self, context: BaseContext, skill_name: str) -> None:
        """手动卸载；语义同 discard（进入 DISCARDED）。"""
        self.discard_skill(context, skill_name)

    @staticmethod
    def expire_idle(context: BaseContext) -> list[str]:
        """
        推进 idle 并淘汰超时 Skill。

        每个 Reason 轮调用一次：对 LOADED 技能 idle_rounds += 1；
        达到 DEFAULT_MAX_IDLE_ROUNDS（3）则 discard。

        返回:
            本轮被 discard 的 skill 名称列表。
        """
        discarded: list[str] = []
        for name, skill in list(context.active_skills.items()):
            if skill.status != SkillStatus.LOADED:
                if skill.status == SkillStatus.DISCARDED:
                    context.active_skills.pop(name, None)
                continue

            skill.idle_rounds += 1
            if skill.idle_rounds >= SkillManager.DEFAULT_MAX_IDLE_ROUNDS:
                skill.status = SkillStatus.DISCARDED
                skill.instruction = None
                context.active_skills.pop(name, None)
                discarded.append(name)

        return discarded
