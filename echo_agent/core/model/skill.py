from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SkillType(Enum):
    """
    Skill 类型
    """
    FILE = "file"  # 本地文件
    HTTP = "http"  # 远端url地址


class SkillFrontmatter(BaseModel):
    """
    Skill Frontmatter 模型: 用于描述SKILL.md中的 YAML frontmatter

    参数:
        name: 技能名称
        description: 技能描述
        metadata: 附加信息(可选)
    """
    name: str
    description: str
    metadata: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def move_allowed_tools_to_metadata(cls, data: Any) -> Any:
        """Accept top-level allowed_tools while storing it as metadata."""
        if not isinstance(data, dict) or "allowed_tools" not in data:
            return data
        normalized = dict(data)
        metadata = dict(normalized.get("metadata") or {})
        metadata["allowed_tools"] = normalized.pop("allowed_tools")
        normalized["metadata"] = metadata
        return normalized

    @property
    def allowed_tools(self) -> list[str] | None:
        """Return metadata.allowed_tools, normalized to non-empty names."""
        if self.metadata is None or "allowed_tools" not in self.metadata:
            return None
        value = self.metadata["allowed_tools"]
        if not isinstance(value, list):
            return []
        return [
            name.strip()
            for name in value
            if isinstance(name, str) and name.strip()
        ]


class SkillPackage(BaseModel):
    """
    Skill Package 模型，用于描述一个 Skill 包

    参数:
        type: skill类型
        url: 路径, 如：本地文件路径、远端url地址
        skill_file: SKILL.md 文件路径
        frontmatter: Skill Frontmatter
        scripts: 可执行脚本
        references: 参考文档
        assets: 资源文件
    """
    type: SkillType
    url: str
    # SKILL.md
    skill_file: str
    frontmatter: SkillFrontmatter
    # 附件
    scripts: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)


class SkillStatus(Enum):
    """
    Skill 状态
    """
    UNLOADED = "unloaded"  # 未加载
    LOADED = "loaded"  # 已加载
    DISCARDED = "discarded"  # 废弃


class SkillRuntimeContext(BaseModel):
    """
    Skill Runtime Context 模型: 用于描述Skill的运行时上下文

    参数:
        status: 生命周期状态（UNLOADED → LOADED → DISCARDED）
        package: Skill 包元数据
        instruction: 已加载的指令正文（DISCARDED 后清空）
        idle_rounds: 连续未触达的用户交互次数；达阈值后自动 discard
    """
    status: SkillStatus
    package: SkillPackage
    instruction: str | None = None
    idle_rounds: int = 0
