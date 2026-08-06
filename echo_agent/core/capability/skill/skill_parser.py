from pathlib import Path
from urllib.parse import urlparse

import yaml

from ....common.network import HttpClient, HttpClientError
from ....utils.url_utils import join_url
from ...model.skill import SkillFrontmatter, SkillPackage, SkillType


class SkillParser:
    """
    Skill 解析器：负责解析 Skill 目录，生成 SkillPackage
    """
    # 支持的Skill文件名
    SKILL_FILE_CANDIDATES = (
            "SKILL.md",
            "Skill.md",
            "skill.md",
        )
    # 标准附属资源目录（不进入 additional_resources）
    STANDARD_RESOURCE_DIRS = frozenset({"scripts", "references", "assets"})

    @staticmethod
    def parse(skill_dir: str) -> SkillPackage:
        skill_type = SkillParser._detect_type(skill_dir)
        if skill_type == SkillType.FILE:
            return SkillParser._parse_file(skill_dir)
        if skill_type == SkillType.HTTP:
            return SkillParser._parse_http(skill_dir)
        raise ValueError(f"Unsupported skill type: {skill_type}")

    @staticmethod
    def _detect_type(skill_dir: str) -> SkillType:
        """
        判断Skill类型
        """
        parsed = urlparse(skill_dir)
        if parsed.scheme in ("http", "https"):
            return SkillType.HTTP
        return SkillType.FILE

    @staticmethod
    def _parse_file(skill_dir: str) -> SkillPackage:
        """
        解析本地Skill
        """
        root = Path(skill_dir)
        if not root.exists():
            raise FileNotFoundError(f"Skill directory not found: {root}")

        skill_file = SkillParser._find_skill_file(root)
        content = skill_file.read_text(encoding="utf-8")
        frontmatter = SkillParser._parse_frontmatter(content)

        return SkillPackage(
            type=SkillType.FILE,
            url=str(root),
            skill_file=skill_file.name,
            frontmatter=frontmatter,
            scripts=SkillParser._get_files(root / "scripts"),
            references=SkillParser._get_files(root / "references"),
            assets=SkillParser._get_files(root / "assets"),
            additional_resources=SkillParser._get_additional_resources(root),
        )

    @staticmethod
    def _parse_http(skill_url: str) -> SkillPackage:
        """
        解析HTTP Skill
        """
        for name in SkillParser.SKILL_FILE_CANDIDATES:
            try:
                # 拼接url
                url = join_url(skill_url, name)
                content = HttpClient.get(url)
                break
            except HttpClientError:
                continue

        frontmatter = SkillParser._parse_frontmatter(content)
        return SkillPackage(
            type=SkillType.HTTP,
            url=skill_url, # 远端url地址
            skill_file=name,
            frontmatter=frontmatter,
        )

    @staticmethod
    def _find_skill_file(skill_dir: Path) -> Path:
        """
        查找Skill描述文件

        支持:
            SKILL.md
            Skill.md
            skill.md

        """
        for name in SkillParser.SKILL_FILE_CANDIDATES:
            path = skill_dir / name
            if path.exists():
                return path

        raise FileNotFoundError(f"No Skill descriptor found: {skill_dir}")

    @staticmethod
    def _parse_frontmatter(content: str) -> SkillFrontmatter:
        """
        解析 YAML Frontmatter
        """
        if not content.startswith("---"):
            raise ValueError("Missing YAML frontmatter")
        
        parts = content.split("---", 2)
        if len(parts) != 3:
            raise ValueError("Invalid YAML frontmatter")

        data = yaml.safe_load(parts[1]) or {}
        if not isinstance(data, dict):
            raise ValueError("Invalid YAML frontmatter: expected a mapping")

        normalized: dict = {
            "name": data.get("name"),
            "description": data.get("description"),
        }
        metadata: dict = {}
        nested = data.get("metadata")
        if isinstance(nested, dict):
            metadata.update(nested)

        for key, value in data.items():
            if key in ("name", "description", "metadata"):
                continue
            metadata[key] = value

        if metadata:
            normalized["metadata"] = metadata

        return SkillFrontmatter.model_validate(normalized)

    @staticmethod
    def _get_files(directory: Path) -> list[str]:
        """
        获取目录下的所有文件
        """
        if not directory.exists():
            return []

        return sorted(
            str(path.relative_to(directory.parent))
            for path in directory.rglob("*")
            if path.is_file()
        )

    @staticmethod
    def _get_additional_resources(skill_root: Path) -> dict[str, list[str]]:
        """
        获取 skill 根下除 scripts/references/assets/SKILL.md 外的附加资源。

        按顶层目录名分组，例如::

            {
                "agents": ["agents/grader.md", ...],
                "eval-viewer": ["eval-viewer/generate_review.py", ...],
            }

        根目录下的非描述文件归入键 ``"."``。
        """
        additional_resources: dict[str, list[str]] = {}
        if not skill_root.exists():
            return additional_resources

        for entry in sorted(skill_root.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir():
                if entry.name in SkillParser.STANDARD_RESOURCE_DIRS:
                    continue
                files = SkillParser._get_files(entry)
                if files:
                    additional_resources[entry.name] = files
                continue

            if not entry.is_file():
                continue
            if entry.name in SkillParser.SKILL_FILE_CANDIDATES:
                continue
            additional_resources.setdefault(".", []).append(entry.name)

        for key in additional_resources:
            additional_resources[key] = sorted(additional_resources[key])
        return additional_resources
