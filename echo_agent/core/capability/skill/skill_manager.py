from typing import Any

from ...graph.schema import BaseContext
from ...model.skill import SkillPackage, SkillRuntimeContext, SkillStatus
from .skill_loader import SkillLoader
from .skill_parser import SkillParser


class SkillManager:
    """
    Skill Manager：Skill管理器, 负责管理Skill的生命周期
    """
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
        return skill_name in context.active_skills

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
        加载Skill
        """
        skill_name = skill_package.frontmatter.name
        if not skill_name:
            raise ValueError("Skill name is required")
        
        # 判断Skill是否已加载
        if skill_name in context.active_skills:
            return context.active_skills[skill_name]
        
        # 加载Skill
        skill_context = SkillLoader.load(skill_package)
        context.active_skills[skill_name] = skill_context
        return skill_context

    def unload_skill(self, context: BaseContext, skill_name: str) -> None:
        """
        卸载Skill
        """
        skill_context = context.active_skills.pop(skill_name, None)
        if skill_context is None:
            return

        skill_context.status = SkillStatus.UNLOADED
