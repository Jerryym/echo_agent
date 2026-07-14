"""将 LangChain / callable 工具导出为 OpenAI Tool JSON Schema 文件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from langchain_core.utils.function_calling import convert_to_openai_tool


def tools_to_json_schema(tools: Iterable[Any]) -> list[dict[str, Any]]:
    """将工具列表转换为 OpenAI Tool JSON Schema 列表。"""
    return [convert_to_openai_tool(tool) for tool in tools]


def export_tool_json_schema(
    tools: Sequence[Any],
    output_path: str | Path,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> Path:
    """将工具的 JSON Schema 写入指定文件。

    Args:
        tools: 可被 ``convert_to_openai_tool`` 转换的工具序列
        output_path: 输出 JSON 文件路径
        indent: JSON 缩进空格数
        ensure_ascii: 是否转义非 ASCII 字符

    Returns:
        写入完成后的输出路径
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = tools_to_json_schema(tools)
    path.write_text(
        json.dumps(schema, ensure_ascii=ensure_ascii, indent=indent),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    from business_tools import BUSINESS_TOOLS

    out = Path(__file__).resolve().parent / "business_tools_schema.json"
    export_tool_json_schema(BUSINESS_TOOLS, out)
    print(f"Wrote {len(BUSINESS_TOOLS)} tool schemas -> {out}")
