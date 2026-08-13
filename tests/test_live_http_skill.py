"""
真实 HTTP Skill 联调（访问远端 manifest，不 mock）

1. 拉取 manifest → SkillPackage
2. 读取 SKILL.md 正文；若清单有资源则再读一项

在下方 LIVE_HTTP_SKILLS 填入 skill_name → url 后运行：
  python tests/test_live_http_skill.py

字典为空时跳过。
"""

from __future__ import annotations

import asyncio
from typing import Any

from echo_agent.core.capability.skill import SkillLoader, SkillParser
from echo_agent.core.model.skill import SkillStatus, SkillType
from echo_agent.core.tool.toolkit.skill import _aread_package_resource, _declared_resource_paths
from echo_agent.utils.url_utils import join_url

LIVE_HTTP_SKILLS: dict[str, Any] = {
    "skill-name": "url"
}


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


def _preview(text: str, limit: int = 400) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "\n... [truncated]"


def _first_declared_resource(package) -> str | None:
    for path in (
        *package.references,
        *package.scripts,
        *package.assets,
        *(item for group in package.additional_resources.values() for item in group),
    ):
        if path and path != package.skill_file:
            return path
    return None


def test_fetch_manifest(skill_name: str, skill_url: str):
    _print("1. GET manifest")
    print(f"name: {skill_name}")
    print(f"url: {skill_url}")
    package = SkillParser.parse(skill_url)

    assert package.type == SkillType.HTTP
    assert package.url == skill_url
    assert package.skill_file
    assert package.frontmatter.name
    assert package.frontmatter.description

    declared = _declared_resource_paths(package)
    print(f"skill_file: {package.skill_file}")
    print(f"frontmatter.name: {package.frontmatter.name}")
    print(f"scripts: {len(package.scripts)}")
    print(f"references: {len(package.references)}")
    print(f"assets: {len(package.assets)}")
    print(f"additional_resources: {len(package.additional_resources)}")
    print(f"declared_paths: {len(declared)}")
    print("ok")
    return package


def test_read_contents(package) -> None:
    _print("2. GET skill_file + resource")
    runtime = SkillLoader.load(package)
    assert runtime.status == SkillStatus.LOADED
    assert runtime.instruction is not None
    assert runtime.instruction.strip()
    print(f"skill_file url: {join_url(package.url, package.skill_file)}")
    print(f"instruction:\n{_preview(runtime.instruction)}")

    target = _first_declared_resource(package)
    if target is None:
        print("no extra resource in manifest; skip resource GET")
        print("ok")
        return

    declared = _declared_resource_paths(package)
    assert target in declared, f"resource not in manifest: {target}"
    content = asyncio.run(_aread_package_resource(package, target))
    assert content is not None
    assert str(content).strip()
    print(f"resource: {target}")
    print(f"resource url: {join_url(package.url, target)}")
    print(f"content:\n{_preview(str(content))}")
    print("ok")


def main() -> None:
    cases = {
        name: url
        for name, url in LIVE_HTTP_SKILLS.items()
        if isinstance(name, str) and name.strip() and isinstance(url, str) and url.strip()
    }
    if not cases:
        print("skip live HTTP skill test: LIVE_HTTP_SKILLS is empty")
        return

    for skill_name, skill_url in cases.items():
        print(f"\n######## {skill_name} ########")
        package = test_fetch_manifest(skill_name, skill_url.strip())
        test_read_contents(package)

    print("\nLive HTTP skill tests passed.")


if __name__ == "__main__":
    main()
