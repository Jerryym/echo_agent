from typing import Any

from ....common import get_logger
from ....common.network import HttpRequest
from ...graph.schema import BaseContext
from ...model.skill import (
    SkillFrontmatter,
    SkillPackage,
    SkillRuntimeContext,
    SkillStatus,
)
from .skill_loader import SkillLoader
from .skill_parser import SkillParser

logger = get_logger("skillmanager")


class SkillManager:
    """
     Skill Manager：Skill管理器, 负责管理Skill的生命周期

    状态机：
        UNLOADED ⇄ LOADED

        UNLOADED ──discard──> DISCARDED
        LOADED   ──discard──> DISCARDED

    状态说明：
        - UNLOADED：Skill 存在且有效，但当前未加载到 active_skills
        - LOADED：Skill 当前已加载到 active_skills
        - DISCARDED：Skill 已失效，不再可用

    参数：
        skill_list: Skill列表
        skill_contexts: Skill运行时上下文
        skill_frontmatter_list: Skill Frontmatter 列表
    """
    DEFAULT_MAX_IDLE_ROUNDS = 3

    def __init__(self, skill_list: dict[str, Any]):
        self._skill_list = skill_list
        self._skill_contexts: dict[str, SkillRuntimeContext] = {}
        self._skill_frontmatter_list = {}

        # 初始化skill contexts
        self._init_skill_contexts()

    @property
    def skill_frontmatter_list(self) -> dict[str, SkillFrontmatter]:
        return self._skill_frontmatter_list

    def build_skill_frontmatter_list(self, http_request: HttpRequest | None = None) -> dict[str, SkillFrontmatter] | None:
        if not self._skill_list:
            return None

        if self._skill_frontmatter_list:
            return self._skill_frontmatter_list

        for name, skill_dir in self._skill_list.items():
            self.build_skill_frontmatter(name, skill_dir, http_request)

        return self._skill_frontmatter_list

    def build_skill_frontmatter(self, skill_name: str, skill_dir: str, http_request: HttpRequest | None = None) -> None:
        try:
            fronmatter = SkillParser.parse(skill_dir, http_request).frontmatter
            self._skill_frontmatter_list[skill_name] = fronmatter
        except Exception as e:
            logger.error(
                "failed to parse skill frontmatter: name=%s, path=%s, error=%s",
                skill_name,
                skill_dir,
                e,
            )

    def get_skill(self, context: BaseContext, skill_name: str) -> SkillRuntimeContext | None:
        """获取Skill"""
        return context.active_skills.get(skill_name)

    def has_skill(self, context: BaseContext, skill_name: str) -> bool:
        """判断Skill是否已加载"""
        skill = context.active_skills.get(skill_name)
        return skill is not None and skill.status == SkillStatus.LOADED

    def load_skill_package(self, skill_name: str, http_request: HttpRequest | None = None) -> SkillPackage:
        """
        根据skill name构建 SkillPackage
        """
        skill_dir = self._skill_list.get(skill_name)
        if skill_dir is None:
            raise ValueError(f"Skill not found: {skill_name}")
        return SkillParser.parse(skill_dir, http_request)

    def load_skill(self, skill_name: str, context: BaseContext, http_request: HttpRequest | None = None) -> SkillRuntimeContext:
        """
        加载Skill
        """
        # skill_name = skill_package.frontmatter.name
        # if not skill_name:
        #     raise ValueError("Skill name is required")

        # existing = context.active_skills.get(skill_name)
        # if existing is not None and existing.status == SkillStatus.LOADED:
        #     existing.idle_rounds = 0
        #     return existing

        # skill_context = SkillLoader.load(skill_package, http_request)
        # skill_context.idle_rounds = 0
        # context.active_skills[skill_name] = skill_context
        # return skill_context

        skill_context = self._skill_contexts.get(skill_name)
        logger.info("skill context: %s", skill_context)
        # skill context 不存在
        if skill_context is None:
            raise ValueError(f"Skill not found: {skill_name}")
        
        logger.info("skill context status: %s", skill_context.status)
        # skill status 为 DISCARDED
        if skill_context.status == SkillStatus.DISCARDED:
            raise ValueError(f"Skill is discarded: {skill_name}")

        # skill status 为 LOADED, 重置idle_rounds
        if skill_context.status == SkillStatus.LOADED:
            skill_context.idle_rounds = 0 # 重置
            context.active_skills[skill_name] = skill_context
            return skill_context
        
        # 加载skill package
        skill_package = self.load_skill_package(skill_name, http_request)
        instruction = SkillLoader.load(skill_package, http_request)
        logger.info("loaded skill instruction: %s", instruction)

        # 更新skill context
        skill_context.status = SkillStatus.LOADED
        skill_context.package = skill_package
        skill_context.instruction = instruction
        skill_context.idle_rounds = 0

        context.active_skills[skill_name] = skill_context
        return skill_context

    def unload_skill(self, skill_name: str, context: BaseContext) -> None:
        """卸载Skill"""
        skill = self._skill_contexts.get(skill_name)
        if skill is None:
            return

        context.active_skills.pop(skill_name, None)

        skill.status = SkillStatus.UNLOADED
        skill.package = None # 清空package
        skill.instruction = "" # 清空instruction
        skill.idle_rounds = 0 # 重置idle_rounds

    def discard_skill(self, skill_name: str, context: BaseContext) -> None:
        """
        废弃 Skill：status → DISCARDED
        """
        skill_context = self._skill_contexts.get(skill_name)
        if skill_context is None:
            return

        context.active_skills.pop(skill_name, None)

        skill_context.status = SkillStatus.DISCARDED
        skill_context.package = None
        skill_context.instruction = ""
        skill_context.idle_rounds = 0

    # @staticmethod
    # def reset_idle_rounds_for_tool(context: BaseContext, tool_name: str, original_name: str | None = None) -> None:
    #     """
    #     执行工具时重置 Skill 的 idle_rounds
    #     """
    #     candidates = {tool_name}
    #     if original_name:
    #         candidates.add(original_name)

    #     for skill in context.active_skills.values():
    #         if skill.status != SkillStatus.LOADED:
    #             continue
    #         allowed = skill.package.frontmatter.allowed_tools
    #         if not allowed:
    #             continue
    #         if candidates & set(allowed):
    #             skill.idle_rounds = 0

    def unload_idle_skills(self, context: BaseContext) -> list[str]:
        """
        卸载超时 Skill
        """
        unloaded: list[str] = []
        for name, skill in list(context.active_skills.items()):
            if skill.status != SkillStatus.LOADED:
                continue
            
            skill.idle_rounds += 1
            # 达到最大idle轮次，卸载skill
            if skill.idle_rounds >= SkillManager.DEFAULT_MAX_IDLE_ROUNDS:
                self.unload_skill(name, context)
                unloaded.append(name)
        return unloaded

    def reset_idle_rounds(self, skill_name: str, context: BaseContext) -> None:
        """重置 Skill 的 idle_rounds 为 0"""
        skill = context.active_skills.get(skill_name)
        if skill is None or skill.status != SkillStatus.LOADED:
            return
        skill.idle_rounds = 0

    def _init_skill_contexts(self) -> None:
        """初始化skill context list"""
        for name in self._skill_list.keys():
            skill_context = SkillRuntimeContext(status=SkillStatus.UNLOADED)
            self._skill_contexts[name] = skill_context
