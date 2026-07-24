"""SKILL.md 解析：YAML Frontmatter + Markdown Body。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*(?:\n(?P<body>.*))?\Z",
    re.DOTALL,
)
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillParseError(Exception):
    """SKILL.md 解析错误。"""


@dataclass(frozen=True)
class SkillDocument:
    """解析后的 SKILL.md。"""

    name: str
    description: str
    body: str
    raw: str


def parse_skill_md(content: str) -> SkillDocument:
    """
    解析 SKILL.md 文本。

    Frontmatter 必填字段：name、description。
    name 须为小写字母、数字与连字符（不可首尾为连字符）。
    """
    if content is None:
        raise SkillParseError("SKILL.md content is empty")

    raw = content.replace("\r\n", "\n").replace("\r", "\n")
    match = _FRONTMATTER_PATTERN.match(raw)
    if match is None:
        raise SkillParseError("SKILL.md must start with YAML frontmatter delimited by ---")

    metadata = _parse_frontmatter(match.group("frontmatter"))
    name = metadata.get("name")
    description = metadata.get("description")

    if not isinstance(name, str) or not name.strip():
        raise SkillParseError("Frontmatter field 'name' is required")
    if not isinstance(description, str) or not description.strip():
        raise SkillParseError("Frontmatter field 'description' is required")

    name = name.strip()
    description = description.strip()
    if len(name) > 64:
        raise SkillParseError("Frontmatter field 'name' must be at most 64 characters")
    if len(description) > 1024:
        raise SkillParseError(
            "Frontmatter field 'description' must be at most 1024 characters"
        )
    if not _NAME_PATTERN.fullmatch(name):
        raise SkillParseError(
            "Frontmatter field 'name' must use lowercase letters, numbers, "
            "and hyphens only"
        )

    body = (match.group("body") or "").strip("\n")
    return SkillDocument(
        name=name,
        description=description,
        body=body,
        raw=raw,
    )


def _parse_frontmatter(text: str) -> dict[str, str]:
    """解析简单 YAML frontmatter（支持 name / description 标量）。"""
    result: dict[str, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if ":" not in line:
            raise SkillParseError(f"Invalid frontmatter line: {line!r}")

        key, _, value = line.partition(":")
        key = key.strip()
        if not key:
            raise SkillParseError(f"Invalid frontmatter key: {line!r}")

        value = value.strip()
        if value in ("|", ">"):
            block_lines: list[str] = []
            i += 1
            while i < len(lines):
                block_line = lines[i]
                if block_line and not block_line.startswith((" ", "\t")):
                    break
                block_lines.append(block_line.strip())
                i += 1
            result[key] = "\n".join(block_lines).strip()
            continue

        result[key] = _unquote(value)
        i += 1

    return result


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
