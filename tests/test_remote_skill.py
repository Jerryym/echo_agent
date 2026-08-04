"""
Remote (HTTP) Skill 单元测试（mock HttpClient，不访问真实网络）

覆盖：
1. SkillParser 类型识别 / HTTP 解析 / 候选文件回退
2. SkillLoader HTTP 加载与失败路径
3. SkillManager 注册远端 skill 并 load

运行：
  uv run python tests/test_remote_skill.py
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from echo_agent.common.network import HttpResponseError
from echo_agent.core.capability.skill import SkillLoader, SkillManager, SkillParser
from echo_agent.core.graph.schema import BaseContext
from echo_agent.core.model.agent_state import AgentState
from echo_agent.core.model.skill import SkillFrontmatter, SkillPackage, SkillStatus, SkillType
from echo_agent.utils.url_utils import join_url

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"

REMOTE_SKILL_NAMES = ("pdf", "docx", "pptx", "xlsx", "skill-creator")

PARSER_GET = "echo_agent.core.capability.skill.skill_parser.HttpClient.get"
LOADER_GET = "echo_agent.core.capability.skill.skill_loader.HttpClient.get"


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


def _skill_md(name: str) -> str:
    path = FIXTURES / name / "SKILL.md"
    assert path.is_file(), f"fixture missing: {path}"
    return path.read_text(encoding="utf-8")


def _base_url(name: str) -> str:
    return f"https://example.com/skills/{name}"


def test_detect_http_type() -> None:
    _print("SkillParser._detect_type")
    assert SkillParser._detect_type("https://example.com/skills/pdf") == SkillType.HTTP
    assert SkillParser._detect_type("http://example.com/skills/pdf") == SkillType.HTTP
    assert SkillParser._detect_type(str(FIXTURES / "pdf")) == SkillType.FILE
    print("ok")


def test_parse_remote_skills_from_fixtures() -> None:
    _print("SkillParser.parse (HTTP fixtures)")
    for name in REMOTE_SKILL_NAMES:
        base = _base_url(name)
        content = _skill_md(name)
        expected_url = join_url(base, "SKILL.md")

        with patch(PARSER_GET, return_value=content) as mock_get:
            package = SkillParser.parse(base)
            print(f"[DEBUG] package: {package.model_dump_json(indent=2)}")

        mock_get.assert_called_once_with(expected_url)
        assert package.type == SkillType.HTTP
        assert package.skill_file == "SKILL.md"
        assert package.url == base
        assert package.frontmatter.name == name
        assert package.frontmatter.description

    print("ok")


def test_parse_http_candidate_fallback() -> None:
    _print("SkillParser._parse_http candidate fallback")
    base = _base_url("pdf")
    content = _skill_md("pdf")

    def fake_get(url: str, **_kwargs: object) -> str:
        if url.endswith("/SKILL.md"):
            raise HttpResponseError(f"HTTP response error: 404, url={url}")
        if url.endswith("/Skill.md"):
            return content
        raise HttpResponseError(f"HTTP response error: 404, url={url}")

    with patch(PARSER_GET, side_effect=fake_get) as mock_get:
        package = SkillParser.parse(base)
        print(f"[DEBUG] package: {package.model_dump_json(indent=2)}")

    assert package.type == SkillType.HTTP
    assert package.skill_file == "Skill.md"
    assert package.url == base
    assert package.frontmatter.name == "pdf"
    assert mock_get.call_count == 2
    print("ok")


def test_parse_http_all_candidates_fail() -> None:
    _print("SkillParser._parse_http all candidates fail")
    with patch(
        PARSER_GET,
        side_effect=HttpResponseError("HTTP response error: 404"),
    ):
        try:
            SkillParser.parse(_base_url("pdf"))
            raise AssertionError("expected parse failure when all candidates fail")
        except Exception:
            pass
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
        print(f"[DEBUG] runtime: {runtime.model_dump_json(indent=2)}")

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


def test_manager_remote_skills() -> None:
    _print("SkillManager with remote skills")
    skill_list = {name: _base_url(name) for name in REMOTE_SKILL_NAMES}

    def fake_parser_get(url: str, **_kwargs: object) -> str:
        for name in REMOTE_SKILL_NAMES:
            if f"/skills/{name}/" in url:
                return _skill_md(name)
        raise HttpResponseError(f"HTTP response error: 404, url={url}")

    with patch(PARSER_GET, side_effect=fake_parser_get):
        manager = SkillManager(skill_list)
        for name in REMOTE_SKILL_NAMES:
            assert name in manager.skill_frontmatter_list
            assert manager.skill_frontmatter_list[name].name == name

        package = manager.build_skill_package("xlsx")
        print(f"[DEBUG] package: {package.model_dump_json(indent=2)}")
        assert package.type == SkillType.HTTP
        assert package.frontmatter.name == "xlsx"

        # Loader 以 package.url + skill_file 再拼一次；mock 任意命中即可
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
    test_parse_http_candidate_fallback()
    test_parse_http_all_candidates_fail()
    test_load_http_success()
    test_load_http_missing_skill_file()
    test_load_http_request_failure()
    test_manager_remote_skills()
    print("\nAll remote skill tests passed.")


if __name__ == "__main__":
    main()
