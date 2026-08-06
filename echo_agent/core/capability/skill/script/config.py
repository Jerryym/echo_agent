"""Skill 脚本执行配置（独立于 AgentConfig）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkillScriptDockerConfig(BaseModel):
    """Docker Runner 配置；仅 runner=docker 时生效。"""

    image: str = "python:3.12-slim"
    network: Literal["none", "bridge"] = "none"
    memory: str | None = None
    cpus: float | None = None


class SkillScriptConfig(BaseModel):
    """
    Skill 包内脚本执行策略。

    不进入 AgentConfig / RuntimeConfig / Adapter proto；
    由宿主在组装 Tool / Runner 时显式传入。
    """

    enabled: bool = False
    runner: Literal["local", "docker"] = "local"
    timeout_sec: int = 60
    max_stdout_bytes: int = 64 * 1024
    max_stderr_bytes: int = 64 * 1024
    allowed_roots: list[str] = Field(default_factory=lambda: ["scripts"])
    require_hitl: bool = False
    workspace_root: str | None = None
    python_executable: str = "python"
    docker: SkillScriptDockerConfig = Field(default_factory=SkillScriptDockerConfig)
