"""Skill Descriptor：Metadata 与 Package 的关联。"""

from __future__ import annotations

from dataclasses import dataclass

from .package import SkillPackage


@dataclass(frozen=True)
class SkillDescriptor:
    """已解析的 Skill 描述（组装期 Metadata + Package）。"""

    name: str
    description: str
    package: SkillPackage
