"""Skill Resolve：由 skill_list 构建只读 Skill 映射。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

from .descriptor import SkillDescriptor
from .package import FileSystemSkillPackage, SkillPackage, SkillPackageError
from .parser import SkillParseError, parse_skill_md

SKILL_ENTRY_FILE = "SKILL.md"


class SkillResolveError(Exception):
    """skill_list 解析失败。"""


@dataclass(frozen=True)
class SkillCatalog:
    """Skill 只读目录（name → SkillDescriptor）。"""

    skills: Mapping[str, SkillDescriptor]

    def get(self, name: str) -> SkillDescriptor | None:
        return self.skills.get(name)

    def list(self) -> list[SkillDescriptor]:
        return list(self.skills.values())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.skills

    def __len__(self) -> int:
        return len(self.skills)


_active_catalog: SkillCatalog | None = None


def set_active_catalog(catalog: SkillCatalog | None) -> None:
    """绑定当前进程内供 load_skill 使用的只读 Skill 映射。"""
    global _active_catalog
    _active_catalog = catalog


def get_active_catalog() -> SkillCatalog | None:
    """获取当前绑定的 Skill 映射。"""
    return _active_catalog


async def resolve_skills(skill_list: Mapping[str, Any] | None) -> SkillCatalog:
    """
    根据 skill_list 构建只读 Skill 映射。

    skill_list:
        key: Skill 名称
        value: 本地 path 或远端 url（Skill Package 根位置）
    """
    if not skill_list:
        return SkillCatalog(skills=MappingProxyType({}))

    resolved: dict[str, SkillDescriptor] = {}
    for name, location in skill_list.items():
        if not isinstance(name, str) or not name.strip():
            raise SkillResolveError(f"Invalid skill name: {name!r}")
        name = name.strip()
        if name in resolved:
            raise SkillResolveError(f"Duplicate skill name: {name}")

        descriptor = await _resolve_one(name, location)
        resolved[name] = descriptor

    return SkillCatalog(skills=MappingProxyType(resolved))


async def _resolve_one(name: str, location: Any) -> SkillDescriptor:
    package = _create_package(name, location)

    try:
        raw = await package.read(SKILL_ENTRY_FILE)
    except SkillPackageError as exc:
        raise SkillResolveError(
            f"Failed to read {SKILL_ENTRY_FILE} for skill '{name}': {exc}"
        ) from exc

    try:
        document = parse_skill_md(raw)
    except SkillParseError as exc:
        raise SkillResolveError(
            f"Failed to parse {SKILL_ENTRY_FILE} for skill '{name}': {exc}"
        ) from exc

    if document.name != name:
        raise SkillResolveError(
            f"Skill name mismatch for '{name}': "
            f"frontmatter name is '{document.name}'"
        )

    return SkillDescriptor(
        name=document.name,
        description=document.description,
        package=package,
    )


def _create_package(name: str, location: Any) -> SkillPackage:
    if location is None:
        raise SkillResolveError(f"Skill '{name}' location is required")

    if not isinstance(location, (str, Path)):
        raise SkillResolveError(
            f"Skill '{name}' location must be path or url string, got {type(location).__name__}"
        )

    location_str = str(location).strip()
    if not location_str:
        raise SkillResolveError(f"Skill '{name}' location is empty")

    if _is_remote_url(location_str):
        raise SkillResolveError(
            f"Remote skill is not supported yet: skill '{name}' -> {location_str}"
        )

    root = _normalize_local_root(location_str)
    try:
        return FileSystemSkillPackage(root)
    except SkillPackageError as exc:
        raise SkillResolveError(
            f"Invalid local skill location for '{name}': {exc}"
        ) from exc


def _is_remote_url(location: str) -> bool:
    parsed = urlparse(location)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_local_root(location: str) -> Path:
    path = Path(location)
    if path.is_file() and path.name == SKILL_ENTRY_FILE:
        return path.parent
    return path
