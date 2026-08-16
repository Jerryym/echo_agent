"""
Remote (HTTP) Skill 单元测试（mock HttpClient，不访问真实网络）

覆盖：
1. SkillParser 类型识别 / HTTP manifest JSON 解析
2. SkillLoader HTTP 加载与失败路径
3. SkillManager 注册远端 skill 并 load
4. HTTP read_skill_resource（清单内 GET / 未声明路径）

运行：
  uv run python tests/test_remote_skill.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from echo_agent.common.network import HttpResponseError
from echo_agent.core.capability.skill import SkillLoader, SkillManager, SkillParser
from echo_agent.core.graph.schema import BaseContext
from echo_agent.core.model.agent import AgentState
from echo_agent.core.model.skill import SkillFrontmatter, SkillPackage, SkillStatus, SkillType
from echo_agent.core.tool.toolkit.skill import _aread_package_resource
from echo_agent.utils.url_utils import join_url

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"

REMOTE_SKILL_NAMES = ("pdf", "docx", "pptx", "xlsx", "skill-creator")

PARSER_GET_JSON = "echo_agent.core.capability.skill.skill_parser.HttpClient.get_json"
LOADER_GET = "echo_agent.core.capability.skill.skill_loader.HttpClient.get"
TOOLKIT_GET = "echo_agent.core.tool.toolkit.skill.HttpClient.get"


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


def _skill_md(name: str) -> str:
    path = FIXTURES / name / "SKILL.md"
    assert path.is_file(), f"fixture missing: {path}"
    return path.read_text(encoding="utf-8")


def _base_url(name: str) -> str:
    return f"https://example.com/skills/{name}"


def _posix_paths(paths: list[str]) -> list[str]:
    return [path.replace("\\", "/") for path in paths]


def _posix_additional(resources: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: _posix_paths(paths) for key, paths in resources.items()}


def _local_package(name: str) -> SkillPackage:
    return SkillParser.parse(str(FIXTURES / name))


def _manifest_from_fixture(
    name: str,
    *,
    remote_type: str = "file",
    remote_url: str = "https://evil.example/other",
) -> dict:
    local = _local_package(name)
    return {
        "type": remote_type,
        "url": remote_url,
        "skill_file": local.skill_file,
        "frontmatter": local.frontmatter.model_dump(),
        "scripts": list(local.scripts),
        "references": list(local.references),
        "assets": list(local.assets),
        "additional_resources": {
            key: list(paths) for key, paths in local.additional_resources.items()
        },
    }


def test_detect_http_type() -> None:
    _print("SkillParser._detect_type")
    assert SkillParser._detect_type("https://example.com/skills/pdf") == SkillType.HTTP
    assert SkillParser._detect_type("http://example.com/skills/pdf") == SkillType.HTTP
    assert SkillParser._detect_type(str(FIXTURES / "pdf")) == SkillType.FILE
    print("ok")


def test_parse_remote_skills_from_fixtures() -> None:
    _print("SkillParser.parse (HTTP manifest)")
    for name in REMOTE_SKILL_NAMES:
        base = _base_url(name)
        local = _local_package(name)
        manifest = _manifest_from_fixture(name)

        with patch(PARSER_GET_JSON, return_value=manifest) as mock_get:
            package = SkillParser.parse(base)

        mock_get.assert_called_once_with(base)
        assert package.type == SkillType.HTTP
        assert package.url == base
        assert package.skill_file == local.skill_file
        assert package.frontmatter.name == name
        assert package.frontmatter.description == local.frontmatter.description
        assert package.scripts == _posix_paths(local.scripts)
        assert package.references == _posix_paths(local.references)
        assert package.assets == _posix_paths(local.assets)
        assert package.additional_resources == _posix_additional(local.additional_resources)
        print(
            f"[DEBUG] {name}: scripts={len(package.scripts)} "
            f"references={len(package.references)} "
            f"assets={len(package.assets)} "
            f"additional={len(package.additional_resources)}"
        )

    print("ok")


def test_parse_http_ignores_remote_type_and_url() -> None:
    _print("SkillParser._parse_http ignores remote type/url")
    base = _base_url("pdf")
    manifest = _manifest_from_fixture(
        "pdf",
        remote_type="file",
        remote_url="https://evil.example/skills/pdf",
    )
    with patch(PARSER_GET_JSON, return_value=manifest):
        package = SkillParser.parse(base)

    assert package.type == SkillType.HTTP
    assert package.url == base
    print("ok")


def test_parse_http_manifest_fetch_fail() -> None:
    _print("SkillParser._parse_http manifest fetch fail")
    base = _base_url("pdf")
    with patch(
        PARSER_GET_JSON,
        side_effect=HttpResponseError("HTTP response error: 404"),
    ):
        try:
            SkillParser.parse(base)
            raise AssertionError("expected parse failure when manifest GET fails")
        except FileNotFoundError as exc:
            message = str(exc)
            assert base in message
            assert "manifest" in message.lower()
        except UnboundLocalError as exc:
            raise AssertionError(
                "HTTP manifest parse must not raise UnboundLocalError"
            ) from exc
    print("ok")


def test_parse_http_missing_frontmatter() -> None:
    _print("SkillParser._parse_http missing frontmatter")
    base = _base_url("pdf")
    with patch(
        PARSER_GET_JSON,
        return_value={"skill_file": "SKILL.md"},
    ):
        try:
            SkillParser.parse(base)
            raise AssertionError("expected ValueError for missing frontmatter")
        except ValueError as exc:
            assert "frontmatter" in str(exc)
    print("ok")


def test_parse_http_invalid_resource_path() -> None:
    _print("SkillParser._parse_http invalid resource path")
    base = _base_url("pdf")
    local = _local_package("pdf")
    manifest = {
        "skill_file": "SKILL.md",
        "frontmatter": local.frontmatter.model_dump(),
        "scripts": ["../escape.py"],
    }
    with patch(PARSER_GET_JSON, return_value=manifest):
        try:
            SkillParser.parse(base)
            raise AssertionError("expected ValueError for invalid path")
        except ValueError as exc:
            assert "invalid path" in str(exc)
    print("ok")


def test_parse_http_empty_lists() -> None:
    _print("SkillParser._parse_http empty resource lists")
    base = _base_url("pdf")
    manifest = {
        "skill_file": "SKILL.md",
        "frontmatter": {"name": "pdf", "description": "pdf skill"},
    }
    with patch(PARSER_GET_JSON, return_value=manifest):
        package = SkillParser.parse(base)
    assert package.scripts == []
    assert package.references == []
    assert package.assets == []
    assert package.additional_resources == {}
    print("ok")


def test_load_http_success() -> None:
    _print("SkillLoader.load (HTTP)")
    content = _skill_md("docx")
    base = _base_url("docx")
    package = SkillPackage(
        type=SkillType.HTTP,
        url=base,
        skill_file="SKILL.md",
        frontmatter=SkillFrontmatter(
            name="docx",
            description="docx skill",
        ),
    )

    with patch(LOADER_GET, return_value=content) as mock_get:
        runtime = SkillLoader.load(package)

    mock_get.assert_called_once_with(join_url(base, "SKILL.md"))
    assert runtime.status == SkillStatus.LOADED
    assert runtime.instruction is not None
    assert "DOCX" in runtime.instruction or "docx" in runtime.instruction.lower()
    assert not runtime.instruction.lstrip().startswith("---")
    print("ok")


def test_load_http_missing_skill_file() -> None:
    _print("SkillLoader._load_http missing skill_file")
    package = SkillPackage(
        type=SkillType.HTTP,
        url=_base_url("pdf"),
        skill_file="",
        frontmatter=SkillFrontmatter(name="pdf", description="pdf"),
    )
    try:
        SkillLoader.load(package)
        raise AssertionError("expected ValueError for empty skill_file")
    except ValueError as exc:
        assert "Skill file is required" in str(exc)
    print("ok")


def test_load_http_request_failure() -> None:
    _print("SkillLoader._load_http request failure")
    base = _base_url("pptx")
    package = SkillPackage(
        type=SkillType.HTTP,
        url=base,
        skill_file="SKILL.md",
        frontmatter=SkillFrontmatter(name="pptx", description="pptx"),
    )
    with patch(
        LOADER_GET,
        side_effect=HttpResponseError("HTTP response error: 500"),
    ):
        try:
            SkillLoader.load(package)
            raise AssertionError("expected ValueError on HTTP failure")
        except ValueError as exc:
            assert "Failed to load HTTP skill" in str(exc)
            assert join_url(base, "SKILL.md") in str(exc)
    print("ok")


def test_aread_http_resource() -> None:
    _print("_aread_package_resource (HTTP)")
    base = _base_url("pdf")
    relative = "references/specification.md"
    package = SkillPackage(
        type=SkillType.HTTP,
        url=base,
        skill_file="SKILL.md",
        frontmatter=SkillFrontmatter(name="pdf", description="pdf"),
        references=[relative],
    )
    body = "# spec\n"

    with patch(TOOLKIT_GET, return_value=body) as mock_get:
        content = asyncio.run(_aread_package_resource(package, relative))

    mock_get.assert_called_once_with(join_url(base, relative))
    assert content == body
    print("ok")


def test_aread_http_undeclared_path() -> None:
    _print("_aread_package_resource (HTTP undeclared)")
    package = SkillPackage(
        type=SkillType.HTTP,
        url=_base_url("pdf"),
        skill_file="SKILL.md",
        frontmatter=SkillFrontmatter(name="pdf", description="pdf"),
        references=["references/specification.md"],
    )
    try:
        asyncio.run(_aread_package_resource(package, "scripts/secret.py"))
        raise AssertionError("expected ValueError for undeclared path")
    except ValueError as exc:
        assert "not declared" in str(exc)
    print("ok")


def test_manager_remote_skills() -> None:
    _print("SkillManager with remote skills")
    skill_list = {name: _base_url(name) for name in REMOTE_SKILL_NAMES}

    def fake_get_json(url: str, **_kwargs: object) -> dict:
        for name in REMOTE_SKILL_NAMES:
            if url == _base_url(name):
                return _manifest_from_fixture(name)
        raise HttpResponseError(f"HTTP response error: 404, url={url}")

    with patch(PARSER_GET_JSON, side_effect=fake_get_json):
        manager = SkillManager(skill_list)
        for name in REMOTE_SKILL_NAMES:
            assert name in manager.skill_frontmatter_list
            assert manager.skill_frontmatter_list[name].name == name

        package = manager.build_skill_package("xlsx")
        assert package.type == SkillType.HTTP
        assert package.url == _base_url("xlsx")
        assert package.frontmatter.name == "xlsx"
        assert package.scripts == _posix_paths(_local_package("xlsx").scripts)

        context = BaseContext(agent_state=AgentState(session_id="remote-test"))
        with patch(LOADER_GET, return_value=_skill_md("xlsx")):
            loaded = manager.load_skill(context, package)

        assert manager.has_skill(context, "xlsx")
        assert loaded.status == SkillStatus.LOADED
        assert loaded.instruction is not None
        assert "XLSX" in loaded.instruction or "xlsx" in loaded.instruction.lower()

    print("ok")


def main() -> None:
    for name in REMOTE_SKILL_NAMES:
        assert (FIXTURES / name / "SKILL.md").is_file(), f"fixture missing: {name}"

    test_detect_http_type()
    test_parse_remote_skills_from_fixtures()
    test_parse_http_ignores_remote_type_and_url()
    test_parse_http_manifest_fetch_fail()
    test_parse_http_missing_frontmatter()
    test_parse_http_invalid_resource_path()
    test_parse_http_empty_lists()
    test_load_http_success()
    test_load_http_missing_skill_file()
    test_load_http_request_failure()
    test_aread_http_resource()
    test_aread_http_undeclared_path()
    test_manager_remote_skills()
    print("\nAll remote skill tests passed.")


if __name__ == "__main__":
    main()
