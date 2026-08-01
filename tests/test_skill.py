"""
Skill 能力单元测试（无需 LLM / 网络）

覆盖：
1. SkillParser
2. SkillLoader / SkillManager
3. load_skill / read_skill_resource 工具

运行：
  uv run python tests/test_skill.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from echo_agent.core.capability.skill import SkillLoader, SkillManager, SkillParser
from echo_agent.core.graph.schema import BaseContext
from echo_agent.core.llm.llm_client import LLMClient
from echo_agent.core.model.agent_state import AgentState
from echo_agent.core.model.skill import SkillStatus, SkillType
from echo_agent.core.tool.toolkit import (
    create_load_skill_tool,
    create_read_skill_resource_tool,
    reset_skill_runtime_context,
    set_skill_runtime_context,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"
PDF_SKILL_DIR = FIXTURES / "pdf"


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


def test_skill_parser() -> None:
    _print("SkillParser")
    package = SkillParser.parse(str(PDF_SKILL_DIR))
    assert package.type == SkillType.FILE
    assert package.frontmatter.name == "pdf"
    assert "PDF" in package.frontmatter.description
    assert package.skill_file == "SKILL.md"
    assert any(path.endswith("specification.md") for path in package.references)

    try:
        SkillParser.parse(str(PDF_SKILL_DIR / "missing"))
        raise AssertionError("expected missing skill dir to fail")
    except FileNotFoundError:
        pass

    print("ok")


def test_skill_loader_and_manager() -> None:
    _print("SkillLoader / SkillManager")
    manager = SkillManager({"pdf": str(PDF_SKILL_DIR)})
    package = manager.build_skill_package("pdf")
    runtime = SkillLoader.load(package)
    assert runtime.status == SkillStatus.LOADED
    assert runtime.instruction is not None
    assert "PDF" in runtime.instruction or len(runtime.instruction) > 0

    context = BaseContext(agent_state=AgentState(session_id="test"))
    loaded = manager.load_skill(context, package)
    assert "pdf" in context.active_skills
    assert manager.has_skill(context, "pdf")
    assert manager.get_skill(context, "pdf") is loaded

    manager.unload_skill(context, "pdf")
    assert "pdf" not in context.active_skills

    try:
        manager.build_skill_package("missing")
        raise AssertionError("expected missing skill to fail")
    except ValueError as exc:
        assert "Skill not found" in str(exc)

    print("ok")


async def test_load_and_read_tools() -> None:
    _print("load_skill / read_skill_resource")

    manager = SkillManager({"pdf": str(PDF_SKILL_DIR)})
    load_skill = create_load_skill_tool(manager)
    read_skill_resource = create_read_skill_resource_tool(manager)

    # 无 runtime context 时返回错误文案
    no_ctx = await load_skill.ainvoke({"name": "pdf"})
    assert "Skill runtime context is not available" in no_ctx

    context = BaseContext(agent_state=AgentState(session_id="test"))
    token = set_skill_runtime_context(context)
    try:
        body = await load_skill.ainvoke({"name": "pdf"})
        assert body == "Skill pdf loaded."
        assert "pdf" in context.active_skills

        unknown = await load_skill.ainvoke({"name": "missing"})
        assert "Skill not found" in unknown

        spec = await read_skill_resource.ainvoke(
            {"name": "pdf", "path": "references/specification.md"}
        )
        assert "UTF-8" in spec or len(spec) > 0

        missing = await read_skill_resource.ainvoke(
            {"name": "pdf", "path": "references/nope.md"}
        )
        assert "Failed to read" in missing

        bad_path = await read_skill_resource.ainvoke(
            {"name": "pdf", "path": "../outside.md"}
        )
        assert "Invalid resource path" in bad_path
    finally:
        reset_skill_runtime_context(token)

    print("ok")


async def test_llm_build_prompt_no_global_catalog() -> None:
    _print("LLMClient._build_prompt (no global catalog)")
    client = object.__new__(LLMClient)

    without = LLMClient._build_prompt(client, "ACTION PROMPT", tool_list=None)
    assert without == "ACTION PROMPT"
    assert "Available Skills" not in without

    fake_tools = [
        {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": "x",
                "parameters": {},
            },
        }
    ]
    with_tools = LLMClient._build_prompt(client, "ACTION PROMPT", tool_list=fake_tools)
    assert "Tool Call Policy" in with_tools
    assert with_tools.endswith("ACTION PROMPT")
    print("ok")


async def main() -> None:
    assert PDF_SKILL_DIR.is_dir(), f"fixture missing: {PDF_SKILL_DIR}"
    test_skill_parser()
    test_skill_loader_and_manager()
    await test_load_and_read_tools()
    await test_llm_build_prompt_no_global_catalog()
    print("\nAll skill tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
