"""
Skill 能力单元测试（无需 LLM / 网络）

覆盖：
1. FileSystemSkillPackage
2. SKILL.md Parser
3. resolve_skills / SkillCatalog
4. Skill Usage Prompt
5. load_skill / read_skill_resource
6. setup_skills 注册
7. LLMClient._build_prompt 注入 Skill Usage Prompt

运行：
  uv run python tests/test_skill.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from echo_agent.core.capability.skill import (
    FileSystemSkillPackage,
    SkillPackageError,
    SkillPackageNotFoundError,
    SkillPackagePathError,
    SkillParseError,
    SkillResolveError,
    build_skill_usage_prompt,
    format_available_skills,
    get_active_catalog,
    parse_skill_md,
    resolve_skills,
    set_active_catalog,
    setup_skills,
)
from echo_agent.core.llm.llm_client import LLMClient
from echo_agent.core.tool import ToolRegistry
from echo_agent.core.tool.toolkit import load_skill, read_skill_resource

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"
PDF_SKILL_DIR = FIXTURES / "pdf"


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


async def test_filesystem_package() -> None:
    _print("FileSystemSkillPackage")
    package = FileSystemSkillPackage(PDF_SKILL_DIR)

    content = await package.read("SKILL.md")
    assert "name: pdf" in content
    assert await package.exists("SKILL.md") is True
    assert await package.exists("missing.md") is False

    entries = await package.list()
    assert "SKILL.md" in entries
    assert "references/" in entries

    refs = await package.list("references")
    assert "references/specification.md" in refs

    try:
        await package.read("../outside.md")
        raise AssertionError("expected path escape to fail")
    except SkillPackagePathError:
        pass

    try:
        await package.read("no-such.md")
        raise AssertionError("expected missing file to fail")
    except SkillPackageNotFoundError:
        pass

    print("ok")


async def test_package_binary_reject() -> None:
    _print("FileSystemSkillPackage binary reject")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
        package = FileSystemSkillPackage(root)
        try:
            await package.read("blob.bin")
            raise AssertionError("expected binary read to fail")
        except SkillPackageError as exc:
            assert "UTF-8" in str(exc)
    print("ok")


def test_parser() -> None:
    _print("parse_skill_md")
    doc = parse_skill_md(
        "---\n"
        "name: pdf\n"
        "description: Create and analyze PDF files.\n"
        "---\n"
        "\n"
        "# PDF Skill\n"
        "\n"
        "Do work.\n"
    )
    assert doc.name == "pdf"
    assert doc.description == "Create and analyze PDF files."
    assert "# PDF Skill" in doc.body
    assert "Do work." in doc.body

    try:
        parse_skill_md("# no frontmatter\n")
        raise AssertionError("expected missing frontmatter to fail")
    except SkillParseError:
        pass

    try:
        parse_skill_md("---\nname: PDF\ndescription: x\n---\n")
        raise AssertionError("expected invalid name to fail")
    except SkillParseError:
        pass

    try:
        parse_skill_md("---\nname: pdf\n---\n")
        raise AssertionError("expected missing description to fail")
    except SkillParseError:
        pass

    print("ok")


async def test_resolve_skills() -> None:
    _print("resolve_skills")
    set_active_catalog(None)

    empty = await resolve_skills({})
    assert len(empty) == 0

    catalog = await resolve_skills({"pdf": str(PDF_SKILL_DIR)})
    assert len(catalog) == 1
    assert "pdf" in catalog
    skill = catalog.get("pdf")
    assert skill is not None
    assert skill.name == "pdf"
    assert "PDF" in skill.description

    # 允许直接传 SKILL.md 路径
    catalog2 = await resolve_skills({"pdf": str(PDF_SKILL_DIR / "SKILL.md")})
    assert catalog2.get("pdf") is not None

    try:
        await resolve_skills({"wrong": str(PDF_SKILL_DIR)})
        raise AssertionError("expected name mismatch to fail")
    except SkillResolveError as exc:
        assert "mismatch" in str(exc)

    try:
        await resolve_skills({"pdf": "https://example.com/skills/pdf/"})
        raise AssertionError("expected remote reject")
    except SkillResolveError as exc:
        assert "Remote" in str(exc)

    print("ok")


async def test_context_prompt() -> None:
    _print("Skill Usage Prompt")
    catalog = await resolve_skills({"pdf": str(PDF_SKILL_DIR)})
    available = format_available_skills(catalog)
    assert "# Available Skills" in available
    assert "pdf:" in available

    prompt = build_skill_usage_prompt(catalog)
    assert prompt is not None
    assert "# Skills" in prompt
    assert "# Available Skills" in prompt
    assert "pdf:" in prompt
    assert build_skill_usage_prompt(await resolve_skills({})) is None
    print("ok")


async def test_load_and_read_tools() -> None:
    _print("load_skill / read_skill_resource")
    set_active_catalog(None)

    no_cfg = await load_skill.ainvoke({"name": "pdf"})
    assert "No skills are configured" in no_cfg

    catalog = await resolve_skills({"pdf": str(PDF_SKILL_DIR)})
    set_active_catalog(catalog)

    body = await load_skill.ainvoke({"name": "pdf"})
    assert "# PDF Skill" in body
    assert "name: pdf" not in body  # body only, no frontmatter

    unknown = await load_skill.ainvoke({"name": "missing"})
    assert "Unknown skill" in unknown
    assert "pdf" in unknown

    spec = await read_skill_resource.ainvoke(
        {"name": "pdf", "path": "references/specification.md"}
    )
    assert "UTF-8" in spec

    missing = await read_skill_resource.ainvoke(
        {"name": "pdf", "path": "references/nope.md"}
    )
    assert "Failed to read" in missing

    bad_path = await read_skill_resource.ainvoke(
        {"name": "pdf", "path": "../outside.md"}
    )
    assert "Invalid resource path" in bad_path

    set_active_catalog(None)
    print("ok")


async def test_setup_skills_register() -> None:
    _print("setup_skills")
    set_active_catalog(None)
    registry = ToolRegistry()
    catalog, prompt = await setup_skills({"pdf": str(PDF_SKILL_DIR)}, registry)

    assert len(catalog) == 1
    assert prompt is not None
    assert get_active_catalog() is catalog

    names = {d.name for d in registry.list_definitions()}
    assert "load_skill" in names
    assert "read_skill_resource" in names

    handler = registry.get_handler("load_skill")
    body = await handler.ainvoke({"name": "pdf"})
    assert "# PDF Skill" in body

    empty_registry = ToolRegistry()
    empty_catalog, empty_prompt = await setup_skills({}, empty_registry)
    assert len(empty_catalog) == 0
    assert empty_prompt is None
    assert empty_registry.list_definitions() == []

    set_active_catalog(None)
    print("ok")


async def test_llm_build_prompt_injects_skill() -> None:
    _print("LLMClient._build_prompt skill inject")
    set_active_catalog(None)

    # 不真正初始化模型，仅复用实例方法
    client = object.__new__(LLMClient)

    without = LLMClient._build_prompt(client, "ACTION PROMPT", tool_list=None)
    assert without == "ACTION PROMPT"
    assert "Available Skills" not in without

    catalog = await resolve_skills({"pdf": str(PDF_SKILL_DIR)})
    set_active_catalog(catalog)

    with_skill = LLMClient._build_prompt(client, "ACTION PROMPT", tool_list=None)
    assert "# Skills" in with_skill
    assert "Available Skills" in with_skill
    assert "pdf:" in with_skill
    assert with_skill.endswith("ACTION PROMPT")

    # tool_list 非空时应同时含 tool policy
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
    with_both = LLMClient._build_prompt(client, "ACTION PROMPT", tool_list=fake_tools)
    assert "Tool Call Policy" in with_both
    assert "# Skills" in with_both

    set_active_catalog(None)
    print("ok")


async def main() -> None:
    assert PDF_SKILL_DIR.is_dir(), f"fixture missing: {PDF_SKILL_DIR}"
    await test_filesystem_package()
    await test_package_binary_reject()
    test_parser()
    await test_resolve_skills()
    await test_context_prompt()
    await test_load_and_read_tools()
    await test_setup_skills_register()
    await test_llm_build_prompt_injects_skill()
    print("\nAll skill tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
