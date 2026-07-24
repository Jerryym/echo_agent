from langchain_core.tools import tool

from ...capability.skill.package import SkillPackageError
from ...capability.skill.parser import parse_skill_md
from ...capability.skill.resolve import SKILL_ENTRY_FILE, get_active_catalog


def _require_skill(name: str):
    catalog = get_active_catalog()
    if catalog is None or len(catalog) == 0:
        return None, "No skills are configured."

    skill = catalog.get(name)
    if skill is None:
        available = ", ".join(s.name for s in catalog.list()) or "(none)"
        return None, f"Unknown skill '{name}'. Available: {available}"
    return skill, None


@tool
async def load_skill(name: str) -> str:
    """
    Load skill instructions.

    Use this tool when the current task requires
    specialized knowledge, workflows, or domain rules
    provided by a skill.

    Args:
        name:
            Skill name.

    Returns:
        Content of SKILL.md.
    """
    skill, error = _require_skill(name)
    if error:
        return error

    raw = await skill.package.read(SKILL_ENTRY_FILE)
    return parse_skill_md(raw).body


@tool
async def read_skill_resource(name: str, path: str) -> str:
    """
    Read an additional resource from a skill package.

    Use this tool when skill instructions reference files under
    references/, scripts/, assets/, or other paths inside the skill.

    Args:
        name:
            Skill name.
        path:
            Relative path inside the skill package
            (e.g. references/specification.md).

    Returns:
        Text content of the skill resource.
    """
    skill, error = _require_skill(name)
    if error:
        return error

    relative = (path or "").strip().replace("\\", "/")
    if not relative or relative in (".", "/"):
        return "Resource path is required."
    if relative.startswith("/") or relative.startswith("../") or "/../" in f"/{relative}/":
        return f"Invalid resource path: {path}"

    try:
        return await skill.package.read(relative)
    except SkillPackageError as exc:
        return f"Failed to read skill resource '{path}' from '{name}': {exc}"
