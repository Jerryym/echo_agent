"""Skill Package：逻辑资源树抽象与本地文件系统实现。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable


class SkillPackageError(Exception):
    """Skill Package 访问错误。"""


class SkillPackagePathError(SkillPackageError):
    """路径非法或越出 Package root。"""


class SkillPackageNotFoundError(SkillPackageError):
    """目标资源不存在。"""


@runtime_checkable
class SkillPackage(Protocol):
    """可访问的 Skill 逻辑资源树。"""

    async def read(self, path: str) -> str:
        """读取相对路径对应的文本内容。"""
        ...

    async def exists(self, path: str) -> bool:
        """判断相对路径是否存在。"""
        ...

    async def list(self, path: str = "") -> list[str]:
        """列出相对路径下的直接子项（相对 Package root 的路径）。"""
        ...


class FileSystemSkillPackage:
    """基于本地文件系统的 Skill Package。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise SkillPackageError(f"Skill package root is not a directory: {self._root}")

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, path: str) -> Path:
        relative = path.strip().replace("\\", "/")
        if relative in ("", "."):
            target = self._root
        else:
            if Path(relative).is_absolute():
                raise SkillPackagePathError(f"Absolute path is not allowed: {path}")
            target = (self._root / relative).resolve()

        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise SkillPackagePathError(
                f"Path escapes skill package root: {path}"
            ) from exc
        return target

    async def read(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise SkillPackageNotFoundError(f"Skill resource not found: {path}")

        def _read_text() -> str:
            try:
                return target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise SkillPackageError(
                    f"Skill resource is not UTF-8 text: {path}"
                ) from exc

        return await asyncio.to_thread(_read_text)

    async def exists(self, path: str) -> bool:
        try:
            target = self._resolve(path)
        except SkillPackagePathError:
            return False
        return await asyncio.to_thread(target.exists)

    async def list(self, path: str = "") -> list[str]:
        target = self._resolve(path)
        if not target.exists():
            raise SkillPackageNotFoundError(f"Skill resource not found: {path or '.'}")
        if not target.is_dir():
            raise SkillPackageError(f"Not a directory: {path or '.'}")

        def _list_entries() -> list[str]:
            entries: list[str] = []
            for child in sorted(target.iterdir(), key=lambda p: p.name):
                rel = child.relative_to(self._root).as_posix()
                if child.is_dir():
                    rel = f"{rel}/"
                entries.append(rel)
            return entries

        return await asyncio.to_thread(_list_entries)
