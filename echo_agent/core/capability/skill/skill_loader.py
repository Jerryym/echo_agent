from pathlib import Path

from ....common.network import HttpClient, HttpClientError
from ....utils import join_url
from ...model.skill import SkillPackage, SkillRuntimeContext, SkillStatus, SkillType


class SkillLoader:
    """
    Skill Loader：Skill加载器, 负责将 SkillPackage 加载为 Runtime Skill
    """
    @staticmethod
    def load(skill_package: SkillPackage) -> SkillRuntimeContext:
        """
        将 SkillPackage 加载为 Runtime Skill
        """
        match skill_package.type:
            case SkillType.FILE:
                content = SkillLoader._load_file(skill_package)
            case SkillType.HTTP:
                content = SkillLoader._load_http(skill_package)
            case _:
                raise ValueError(f"Unsupported skill type: {skill_package.type}")

        return SkillRuntimeContext(
            status=SkillStatus.LOADED,
            package=skill_package,
            instruction=content,
        )

    @staticmethod
    def _load_file(skill_package: SkillPackage) -> str:
        """
        加载Skill.md正文
        """
        skill_path = Path(skill_package.url) / skill_package.skill_file
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_path}")
        content = skill_path.read_text(encoding="utf-8")
        return SkillLoader._extract_instruction(content)

    @staticmethod
    def _load_http(skill_package: SkillPackage) -> str:
        """
        按远端返回的manifest拉取SKILL.md
        """
        if not skill_package.skill_file:
            raise ValueError("Skill file is required for HTTP skill")

        url = join_url(skill_package.url, skill_package.skill_file)
        try:
            content = HttpClient.get(url)
        except HttpClientError as exc:
            raise ValueError(f"Failed to load HTTP skill: {url}") from exc
        return SkillLoader._extract_instruction(content)

    @staticmethod
    def _extract_instruction(content: str) -> str:
        """
        提取Skill.md正文
        """
        if not content.startswith("---"):
            return content

        parts = content.split("---", 2)
        if len(parts) != 3:
            return content

        return parts[2].strip()
