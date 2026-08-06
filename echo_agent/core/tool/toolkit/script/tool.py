"""run_script 内置工具：绑定 SkillManager + Runner + SkillScriptConfig。"""

from __future__ import annotations

from langchain_core.tools import tool

from ....capability.skill import SkillManager
from ....capability.skill.script import (
    ScriptResult,
    ScriptValidationError,
    SkillScriptConfig,
    SkillScriptRunner,
    validate_run_script_request,
)
from ..skill import get_skill_runtime_context


def format_script_result(result: ScriptResult) -> str:
    """将 ScriptResult 格式化为模型可读的 observation 字符串。"""
    stdout = result.stdout
    stderr = result.stderr
    if result.truncated_stdout and "[truncated]" not in stdout:
        stdout = f"{stdout}\n[truncated]" if stdout else "[truncated]"
    if result.truncated_stderr and "[truncated]" not in stderr:
        stderr = f"{stderr}\n[truncated]" if stderr else "[truncated]"

    lines = [f"exit_code: {result.exit_code}"]
    if result.timed_out:
        lines.append("timed_out: true")
    lines.extend(["stdout:", stdout, "stderr:", stderr])
    return "\n".join(lines)


def create_run_script_tool(
    skill_manager: SkillManager,
    runner: SkillScriptRunner,
    config: SkillScriptConfig,
):
    """
    创建绑定到指定 SkillManager / Runner / Config 的 run_script 工具。

    仅应在 ``config.enabled`` 为 true 时由宿主注册；工具内仍做防御性检查。
    """

    @tool
    async def run_script(
        name: str,
        path: str,
        argv: list[str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> str:
        """
        Execute a Python script inside a loaded skill package.

        Use only when skill instructions ask you to run a package script
        (typically under scripts/). You must call load_skill first.
        Do not invent arbitrary host shell commands; to read files use
        read_skill_resource instead.

        Args:
            name: Skill name declared in AgentConfig.skill_list.
            path: Relative path inside the skill package
                (e.g. scripts/package_skill.py).
            argv: Optional argument list passed to the script
                (list of strings; do not use shell quoting).
            cwd: Optional working directory relative to workspace_root
                (if configured) or the skill root. Defaults to skill root.
            timeout_sec: Optional timeout override in seconds.
        """
        if not config.enabled:
            return "Script execution is disabled (SkillScriptConfig.enabled=false)."

        try:
            context = get_skill_runtime_context()
        except RuntimeError as exc:
            return str(exc)

        if not skill_manager.has_skill(context, name):
            return (
                f"Skill '{name}' is not loaded. "
                "Call load_skill before run_script."
            )

        try:
            package = skill_manager.build_skill_package(name)
            validated = validate_run_script_request(
                package=package,
                path=path,
                args=argv,
                cwd=cwd,
                timeout_sec=timeout_sec,
                config=config,
            )
        except ScriptValidationError as exc:
            return str(exc)
        except Exception as exc:
            return f"Failed to prepare script '{path}' for skill '{name}': {exc}"

        if config.require_hitl:
            # HITL 挂接在后续阶段；开启时先拒绝执行，避免绕过审批。
            return (
                "Script execution requires human approval "
                f"(require_hitl=true): name={name!r}, path={path!r}, "
                f"argv={validated.argv!r}, runner={config.runner!r}, "
                f"timeout_sec={validated.timeout_sec}."
            )

        env = {"PYTHONPATH": str(validated.skill_root)}
        try:
            result = await runner.run(
                skill_root=validated.skill_root,
                script=validated.script,
                argv=validated.argv,
                cwd=validated.cwd,
                env=env,
                timeout_sec=validated.timeout_sec,
            )
        except Exception as exc:
            return f"Failed to run script '{path}' for skill '{name}': {exc}"

        skill_manager.touch_skill(context, name)
        return format_script_result(result)

    return run_script
