"""AIMessage content 拆分：正文与模型 reasoning（与 LLMResult 字段同源）。"""

from __future__ import annotations

from typing import Any, Sequence


def split_content_blocks(blocks: Sequence[Any]) -> tuple[list[str], list[str]]:
    """
    拆分 content block 列表为正文片段与 reasoning 片段。
    """
    text_blocks: list[str] = []
    reasoning_blocks: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            text_blocks.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                text_blocks.append(block.get("text", "") or "")
            elif block_type == "reasoning":
                reasoning_text = block.get("reasoning", "") or ""
                if reasoning_text:
                    reasoning_blocks.append(reasoning_text)
            elif block_type in ("image", "audio", "video", "file"):
                text_blocks.append(f"\n[{block_type.upper()} OUTPUT]\n")
        elif hasattr(block, "type"):
            if block.type == "text":
                text_blocks.append(getattr(block, "text", "") or "")
            elif block.type == "reasoning":
                reasoning_text = getattr(block, "reasoning", "") or ""
                if reasoning_text:
                    reasoning_blocks.append(reasoning_text)
    return text_blocks, reasoning_blocks


def split_ai_content(content: Any) -> tuple[str, str]:
    """
    规范化 AIMessage content，分离正文与模型 reasoning。

    Returns:
        (text, reasoning): text 含 text 块与多模态占位；reasoning 为
        type=reasoning 块拼接文本（不写入 text）。语义与 LLMResult.content /
        LLMResult.reasoning 一致。
    """
    if content is None:
        return "", ""

    if isinstance(content, str):
        return content, ""

    if isinstance(content, list):
        text_blocks, reasoning_blocks = split_content_blocks(content)
        return "".join(text_blocks).strip(), "\n".join(reasoning_blocks).strip()

    return str(content), ""
