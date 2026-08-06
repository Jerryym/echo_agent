"""Skill 脚本执行 Runner 协议与结果模型。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ScriptResult(BaseModel):
    """脚本执行结果（经截断后交给 Tool 格式化）。"""

    exit_code: int
    stdout: str
    stderr: str
    truncated_stdout: bool = False
    truncated_stderr: bool = False
    timed_out: bool = False


class SkillScriptRunner(Protocol):
    """可插拔脚本执行后端（local / docker）。"""

    async def run(
        self,
        *,
        skill_root: Path,
        script: Path,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_sec: float,
    ) -> ScriptResult: ...
