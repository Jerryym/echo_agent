"""Skill 内置工具：由 Agent 通过工厂绑定 SkillManager 后注册。"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from pathlib import Path

from langchain_core.tools import tool

from ...capability.skill import SkillManager
from ...graph.schema import BaseContext
from ...model.skill import SkillPackage, SkillType

_skill_runtime_context: ContextVar[BaseContext | None] = ContextVar(
    "skill_runtime_context",
    default=None,
)


def set_skill_runtime_context(context: BaseContext | None):
    """在 ToolNode 执行期绑定 Runtime Context，供 skill 工具写入 active_skills。"""
    return _skill_runtime_context.set(context)


def reset_skill_runtime_context(token) -> None:
    _skill_runtime_context.reset(token)


def get_skill_runtime_context() -> BaseContext:
    context = _skill_runtime_context.get()
    if context is None:
        raise RuntimeError("Skill runtime context is not available")
    return context


def _validate_resource_path(path: str) -> str | None:
    relative = (path or "").strip().replace("\\", "/")
    if not relative or relative in (".", "/"):
        return None
    if relative.startswith("/") or relative.startswith("../") or "/../" in f"/{relative}/":
        return None
    return relative


async def _aread_package_resource(package: SkillPackage, relative: str) -> str:
    if package.type != SkillType.FILE:
        raise NotImplementedError(f"Unsupported skill type for resource read: {package.type}")

    root = Path(package.url).resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes skill package root: {relative}") from exc
    if not target.is_file():
        raise FileNotFoundError(f"Skill resource not found: {relative}")

    def _read_text() -> str:
        return target.read_text(encoding="utf-8")

    return await asyncio.to_thread(_read_text)


def create_load_skill_tool(skill_manager: SkillManager):
    """创建绑定到指定 SkillManager 的 load_skill 工具。"""

    @tool
    async def load_skill(name: str) -> str:
        """
        Load skill instructions into the runtime context.

        Use this tool when the current task requires specialized knowledge,
        workflows, or domain rules provided by a skill.

        Args:
            name: Skill name declared in AgentConfig.skill_list.
        """
        try:
            context = get_skill_runtime_context()
            skill_package = skill_manager.build_skill_package(name)
            skill_manager.load_skill(context=context, skill_package=skill_package)
            return f"Skill {name} loaded."
        except Exception as exc:
            return str(exc)

    return load_skill


def create_read_skill_resource_tool(skill_manager: SkillManager):
    """创建绑定到指定 SkillManager 的 read_skill_resource 工具。"""

    @tool
    async def read_skill_resource(name: str, path: str) -> str:
        """
        Read an additional resource from a skill package.

        Use this tool when skill instructions reference files under
        references/, scripts/, assets/, or other paths inside the skill.

        Args:
            name: Skill name.
            path: Relative path inside the skill package
                (e.g. references/specification.md).
        """
        relative = _validate_resource_path(path)
        if relative is None:
            if not (path or "").strip():
                return "Resource path is required."
            return f"Invalid resource path: {path}"

        try:
            context = get_skill_runtime_context()
            skill_package = skill_manager.build_skill_package(name)
            content = await _aread_package_resource(skill_package, relative)
            skill_manager.touch_skill(context, name)
            return content
        except Exception as exc:
            return f"Failed to read skill resource '{path}' from '{name}': {exc}"

    return read_skill_resource
