from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillType(Enum):
    """
    Skill 类型
    """
    FILE = "file"  # 本地文件
    HTTP = "http"  # 远端url地址


class SkillStatus(Enum):
    """
    Skill 状态
    """
    UNLOADED = "unloaded"  # 未加载
    LOADED = "loaded"  # 已加载
    DISCARDED = "discarded"  # 废弃


class SkillSource(BaseModel):
    """
    Skill Source: 描述Skill来源

    参数:
        name: Skill名称
        url: 地址(本地文件路径、远端url地址)
    """
    name: str
    url: str


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
    def fold_extra_fields_into_metadata(cls, data: Any) -> Any:
        """保持 name/description；将所有其他顶层字段折叠到 metadata 中"""
        if not isinstance(data, dict):
            return data

        normalized: dict[str, Any] = {
            "name": data.get("name"),
            "description": data.get("description"),
        }
        metadata: dict[str, Any] = {}
        nested = data.get("metadata")
        if isinstance(nested, dict):
            metadata.update(nested)

        for key, value in data.items():
            if key in ("name", "description", "metadata"):
                continue
            metadata[key] = value

        if metadata:
            normalized["metadata"] = metadata
        elif "metadata" in data and data["metadata"] is None:
            normalized["metadata"] = None

        return normalized

    @property
    def allowed_tools(self) -> list[str] | None:
        """返回 metadata.allowed_tools，并将其标准化为非空名称列表"""
        if self.metadata is None or "allowed_tools" not in self.metadata:
            return None
        value = self.metadata["allowed_tools"]
        if not isinstance(value, list):
            raise ValueError(f"Skill {self.name!r}: metadata.allowed_tools must be a list, got {type(value).__name__}; treating as unset (no restriction).")
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
        additional_resources: 附加资源，除去scripts/references/assets/外的其他资源
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
    additional_resources: dict[str, list[str]] = Field(default_factory=dict)


class SkillRuntimeContext(BaseModel):
    """
    Skill Runtime Context 模型: 用于描述Skill的运行时上下文

    参数:
        status: 生命周期状态
        package: Skill包
        instruction: 已加载的Skill正文（UNLOADED 后清空）
        idle_rounds: 连续未触达的用户交互次数；达阈值后自动 UNLOADED
    """
    status: SkillStatus = Field(default=SkillStatus.UNLOADED)
    package: SkillPackage | None = None
    instruction: str = Field(default="")
    idle_rounds: int = 0


class SkillResourcePayload(BaseModel):
    """
    Skill Resource Payload 模型: 用于描述Skill资源

    Args:
        path: 资源路径
        content: 资源内容
        binary: 是否为二进制文件
        content_type: 资源类型
        size: 资源大小
    """
    model_config = ConfigDict(populate_by_name=True)

    path: str
    content: str
    binary: bool = False
    content_type: str | None = Field(default=None, alias="contentType")
    size: int | None = None
