"""Skill 组装接入：Resolve → 绑定 catalog → 注册 Skill Tools → Skill Usage Prompt。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...tool import ToolRegistry
from ...tool.toolkit import load_skill, read_skill_resource
from ...tool.utils import to_tool_definition
from .context import build_skill_usage_prompt
from .resolve import SkillCatalog, resolve_skills, set_active_catalog


async def setup_skills(
    skill_list: Mapping[str, Any] | None,
    registry: ToolRegistry,
) -> tuple[SkillCatalog, str | None]:
    """
    组装期接入 Skill 能力。

    1. Resolve skill_list
    2. 绑定只读 catalog（供 load_skill / read_skill_resource / LLM prompt 使用）
    3. 非空时注册 load_skill、read_skill_resource 到 ToolRegistry
    4. 返回 Skill Usage Prompt（无 skill 时为 None）
    """
    catalog = await resolve_skills(skill_list)
    set_active_catalog(catalog)

    if not catalog:
        return catalog, None

    registry.register(to_tool_definition(load_skill), load_skill)
    registry.register(to_tool_definition(read_skill_resource), read_skill_resource)
    return catalog, build_skill_usage_prompt(catalog)
