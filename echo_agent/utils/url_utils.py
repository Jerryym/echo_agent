from urllib.parse import urljoin


def join_url(base_url: str, path: str) -> str:
    """
    拼接url

    参数:
        base_url:
            基础 URL

        path:
            子路径

    示例:
        join_url(
            "https://example.com/skills/code-review",
            "SKILL.md"
        )

        return:
            https://example.com/skills/code-review/SKILL.md
    """
    if not base_url:
        raise ValueError("base_url is required")

    if not path:
        return base_url.rstrip("/")

    return urljoin(
        base_url.rstrip("/") + "/",
        path.lstrip("/"),
    )