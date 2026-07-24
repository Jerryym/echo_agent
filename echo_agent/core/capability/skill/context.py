"""Skill Usage Prompt / Available Skills 文案。"""

from __future__ import annotations

from echo_agent.prompt import PromptLoader

from .resolve import SkillCatalog

_SKILL_USAGE_POLICY_PATH = "prompt/skill_usage_policy.md"


def format_available_skills(catalog: SkillCatalog) -> str:
    """生成 Available Skills 名单（仅 name + description）。"""
    if not catalog:
        return ""

    lines = ["# Available Skills", ""]
    for skill in catalog.list():
        lines.append(f"- {skill.name}: {skill.description}")
    return "\n".join(lines)


def build_skill_usage_prompt(catalog: SkillCatalog) -> str | None:
    """
    组装 Skill Usage Prompt：固定规则 + Available Skills。

    catalog 为空时返回 None（不注入）。
    """
    if not catalog:
        return None

    policy = PromptLoader.load(_SKILL_USAGE_POLICY_PATH).rstrip()
    available = format_available_skills(catalog)
    if not available:
        return policy
    return f"{policy}\n\n{available}"
