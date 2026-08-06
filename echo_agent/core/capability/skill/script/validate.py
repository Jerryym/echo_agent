"""run_script 路径 / 白名单 / cwd 等硬约束校验。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ....model.skill import SkillPackage, SkillType
from .config import SkillScriptConfig


class ScriptValidationError(ValueError):
    """脚本执行请求校验失败。"""


@dataclass(frozen=True)
class ValidatedScriptRequest:
    skill_root: Path
    script: Path
    argv: list[str]
    cwd: Path
    timeout_sec: float


def normalize_relative_path(path: str) -> str | None:
    """
    规范化相对路径；非法则返回 None。

    拒绝：空、绝对路径、含 ``..`` 逃逸。
    """
    relative = (path or "").strip().replace("\\", "/")
    if not relative or relative in (".", "/"):
        return None
    if relative.startswith("/") or relative.startswith("../") or "/../" in f"/{relative}/":
        return None
    # Windows drive / UNC
    if len(relative) >= 2 and relative[1] == ":":
        return None
    if relative.startswith("//"):
        return None

    cleaned: list[str] = []
    for part in Path(relative).parts:
        if part in ("", "."):
            continue
        if part == "..":
            return None
        cleaned.append(part)
    if not cleaned:
        return None
    return "/".join(cleaned)


def is_under_allowed_roots(relative: str, allowed_roots: list[str]) -> bool:
    """相对路径是否落在 allowed_roots 前缀下。"""
    norm = relative.replace("\\", "/").lstrip("./")
    for root in allowed_roots:
        root_norm = (root or "").strip().replace("\\", "/").strip("/")
        if not root_norm:
            continue
        if norm == root_norm or norm.startswith(root_norm + "/"):
            return True
    return False


def _ensure_under(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ScriptValidationError(f"{label} escapes allowed root: {path}") from exc
    return resolved


def _resolve_cwd(
    cwd: str | None,
    *,
    skill_root: Path,
    config: SkillScriptConfig,
) -> Path:
    if cwd is None or not str(cwd).strip():
        return skill_root

    relative = normalize_relative_path(cwd)
    if relative is None:
        raise ScriptValidationError(f"Invalid cwd: {cwd}")

    if config.workspace_root:
        workspace = Path(config.workspace_root).resolve()
        candidate = (workspace / relative).resolve()
        under_workspace = _is_relative_to(candidate, workspace)
        under_skill = _is_relative_to(candidate, skill_root)
        if not under_workspace and not under_skill:
            raise ScriptValidationError(
                f"cwd escapes workspace_root and skill root: {cwd}"
            )
        if not candidate.is_dir():
            raise ScriptValidationError(f"cwd is not a directory: {cwd}")
        return candidate

    candidate = (skill_root / relative).resolve()
    _ensure_under(candidate, skill_root, label="cwd")
    if not candidate.is_dir():
        raise ScriptValidationError(f"cwd is not a directory: {cwd}")
    return candidate


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_run_script_request(
    *,
    package: SkillPackage,
    path: str,
    args: list[str] | None,
    cwd: str | None,
    timeout_sec: int | None,
    config: SkillScriptConfig,
) -> ValidatedScriptRequest:
    """
    在调用 Runner 前统一校验。

    失败抛出 ``ScriptValidationError``（消息可直接返回给模型）。
    """
    if package.type != SkillType.FILE:
        raise ScriptValidationError(
            f"Script execution is only supported for FILE skills, got: {package.type}"
        )

    relative = normalize_relative_path(path)
    if relative is None:
        if not (path or "").strip():
            raise ScriptValidationError("Script path is required.")
        raise ScriptValidationError(f"Invalid script path: {path}")

    if not is_under_allowed_roots(relative, config.allowed_roots):
        allowed = ", ".join(config.allowed_roots) or "(none)"
        raise ScriptValidationError(
            f"Script path not under allowed_roots [{allowed}]: {path}"
        )

    if not relative.lower().endswith(".py"):
        raise ScriptValidationError(
            f"Only .py scripts are supported in v0.1.0, got: {path}"
        )

    if args is None:
        argv: list[str] = []
    else:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ScriptValidationError("args must be a list of strings.")
        argv = list(args)

    effective_timeout = config.timeout_sec if timeout_sec is None else timeout_sec
    if not isinstance(effective_timeout, int) or effective_timeout <= 0:
        raise ScriptValidationError(
            f"timeout_sec must be a positive int, got: {timeout_sec}"
        )

    skill_root = Path(package.url).resolve()
    if not skill_root.is_dir():
        raise ScriptValidationError(f"Skill root is not a directory: {skill_root}")

    script = (skill_root / relative).resolve()
    _ensure_under(script, skill_root, label="script path")
    if not script.is_file():
        raise ScriptValidationError(f"Script file not found: {path}")

    resolved_cwd = _resolve_cwd(cwd, skill_root=skill_root, config=config)

    return ValidatedScriptRequest(
        skill_root=skill_root,
        script=script,
        argv=argv,
        cwd=resolved_cwd,
        timeout_sec=float(effective_timeout),
    )
