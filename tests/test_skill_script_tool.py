"""
Skill script execution（Tool + 校验）单元测试

覆盖：
1. 路径规范化 / allowed_roots / 逃逸
2. create_run_script_tool（mock runner；未启用 / 未 load / 成功路径）

运行：
  uv run python tests/test_skill_script_tool.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from echo_agent.core.capability.skill import SkillManager, SkillParser
from echo_agent.core.capability.skill.script import (
    ScriptResult,
    SkillScriptConfig,
    normalize_relative_path,
    validate_run_script_request,
)
from echo_agent.core.capability.skill.script.validate import (
    ScriptValidationError,
    is_under_allowed_roots,
)
from echo_agent.core.graph.schema import BaseContext
from echo_agent.core.model.agent_state import AgentState
from echo_agent.core.tool.toolkit import (
    create_run_script_tool,
    reset_skill_runtime_context,
    set_skill_runtime_context,
)


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


def _write_demo_skill(root: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "echo_hi.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "SKILL.md").write_text(
        "---\nname: script_demo\ndescription: script demo\n---\n\nRun scripts/echo_hi.py\n",
        encoding="utf-8",
    )


def test_normalize_and_allowed_roots() -> None:
    _print("normalize_relative_path / allowed_roots")
    assert normalize_relative_path("scripts/foo.py") == "scripts/foo.py"
    assert normalize_relative_path(r"scripts\foo.py") == "scripts/foo.py"
    assert normalize_relative_path("../outside.py") is None
    assert normalize_relative_path("scripts/../../etc/passwd") is None
    assert normalize_relative_path("/abs/path.py") is None
    assert normalize_relative_path("") is None

    assert is_under_allowed_roots("scripts/a.py", ["scripts"])
    assert not is_under_allowed_roots("references/a.md", ["scripts"])
    assert is_under_allowed_roots("eval-viewer/x.py", ["scripts", "eval-viewer"])
    print("ok")


def test_validate_run_script_request() -> None:
    _print("validate_run_script_request")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_demo_skill(root)
        package = SkillParser.parse(str(root))
        config = SkillScriptConfig(enabled=True)
        script = (root / "scripts" / "echo_hi.py").resolve()

        ok = validate_run_script_request(
            package=package,
            path="scripts/echo_hi.py",
            args=["--flag"],
            cwd=None,
            timeout_sec=None,
            config=config,
        )
        assert ok.script == script
        assert ok.argv == ["--flag"]
        assert ok.cwd == Path(package.url).resolve()
        assert ok.timeout_sec == 60.0

        try:
            validate_run_script_request(
                package=package,
                path="../hello.py",
                args=None,
                cwd=None,
                timeout_sec=None,
                config=config,
            )
            raise AssertionError("expected path escape to fail")
        except ScriptValidationError as exc:
            assert "Invalid script path" in str(exc)

        try:
            validate_run_script_request(
                package=package,
                path="references/x.py",
                args=None,
                cwd=None,
                timeout_sec=None,
                config=config,
            )
            raise AssertionError("expected allowed_roots reject")
        except ScriptValidationError as exc:
            assert "allowed_roots" in str(exc)

        try:
            validate_run_script_request(
                package=package,
                path="scripts/hello.sh",
                args=None,
                cwd=None,
                timeout_sec=None,
                config=config,
            )
            raise AssertionError("expected non-py reject")
        except ScriptValidationError as exc:
            assert ".py" in str(exc)

    print("ok")


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return ScriptResult(exit_code=0, stdout="hello\n", stderr="")


async def test_create_run_script_tool() -> None:
    _print("create_run_script_tool")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_demo_skill(root)

        manager = SkillManager({"script_demo": str(root)})
        runner = _FakeRunner()
        disabled = create_run_script_tool(
            manager, runner, SkillScriptConfig(enabled=False)
        )
        enabled = create_run_script_tool(
            manager, runner, SkillScriptConfig(enabled=True)
        )

        msg = await disabled.ainvoke(
            {"name": "script_demo", "path": "scripts/echo_hi.py"}
        )
        assert "disabled" in msg.lower()
        assert runner.calls == []

        context = BaseContext(agent_state=AgentState(session_id="script-test"))
        token = set_skill_runtime_context(context)
        try:
            not_loaded = await enabled.ainvoke(
                {"name": "script_demo", "path": "scripts/echo_hi.py"}
            )
            assert "not loaded" in not_loaded.lower()

            package = manager.build_skill_package("script_demo")
            manager.load_skill(context, package)

            escape = await enabled.ainvoke(
                {"name": "script_demo", "path": "../outside.py"}
            )
            assert "Invalid script path" in escape

            body = await enabled.ainvoke(
                {
                    "name": "script_demo",
                    "path": "scripts/echo_hi.py",
                    "argv": ["a"],
                }
            )
            assert "exit_code: 0" in body
            assert "hello" in body
            assert len(runner.calls) == 1
            assert runner.calls[0]["argv"] == ["a"]
            assert context.active_skills["script_demo"].idle_rounds == 0

            hitl_tool = create_run_script_tool(
                manager,
                runner,
                SkillScriptConfig(enabled=True, require_hitl=True),
            )
            denied = await hitl_tool.ainvoke(
                {"name": "script_demo", "path": "scripts/echo_hi.py"}
            )
            assert "approval" in denied.lower()
            assert len(runner.calls) == 1
        finally:
            reset_skill_runtime_context(token)

    print("ok")


async def _main() -> None:
    test_normalize_and_allowed_roots()
    test_validate_run_script_request()
    await test_create_run_script_tool()
    print("\nAll skill script tool tests passed.")


if __name__ == "__main__":
    asyncio.run(_main())
