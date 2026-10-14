import json
from collections.abc import Iterator
from typing import Any

from ..model.tool import ToolResult, ToolResultChunk


class ToolResultReader:
    """
    工具结果内容读取器: 按需生成工具结果内容块，支持大文本或结构化数据的分块读取。
    """
    # 默认字节块大小
    DEFAULT_CHUNK_SIZE = 16 * 1024

    def read(self, result: ToolResult, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[ToolResultChunk]:
        """按需生成工具结果内容块"""
        if chunk_size < 4:
            raise ValueError("chunk_size must be at least 4 UTF-8 bytes")

        contents = self._iter_chunk_contents(result.result, chunk_size)
        current = next(contents, None)
        if current is None:
            yield ToolResultChunk(
                content="",
                offset=0,
                next_offset=0,
                eof=True,
            )
            return

        offset = 0
        # 预读下一块，以准确确定当前块是否为 EOF
        for following in contents:
            next_offset = offset + len(current.encode("utf-8"))
            yield ToolResultChunk(
                content=current,
                offset=offset,
                next_offset=next_offset,
                eof=False,
            )

            offset = next_offset
            current = following

        next_offset = offset + len(current.encode("utf-8"))
        yield ToolResultChunk(
            content=current,
            offset=offset,
            next_offset=next_offset,
            eof=True,
        )

    def _iter_chunk_contents(self, value: Any, chunk_size: int) -> Iterator[str]:
        """按 UTF-8 字节预算组装文本块"""
        buffer = bytearray()
        for unit in self._iter_text_units(value):
            data = unit.encode("utf-8")

            # 当前单元能够完整放入缓冲区
            if len(data) + len(buffer) <= chunk_size:
                buffer.extend(data)
                continue

            # 优先在结构化单元边界结束当前 Chunk
            if buffer:
                yield buffer.decode("utf-8")
                buffer.clear()

            # 超大单元按 UTF-8 字符边界继续切分
            start = 0

            while len(data) - start > chunk_size:
                end = start + chunk_size

                # 避免将多字节字符从中间截断
                while (end > start and (data[end] & 0xC0) == 0x80):
                    end -= 1

                if end == start:
                    raise ValueError("chunk_size cannot fit the next UTF-8 character")

                yield data[start:end].decode("utf-8")
                start = end

            buffer.extend(data[start:])

        if buffer:
            yield buffer.decode("utf-8")

    @staticmethod
    def _iter_text_units(value: Any,) -> Iterator[str]:
        """将工具结果转换为连续的逻辑文本单元"""
        if isinstance(value, str):
            yield value

        elif isinstance(value, list):
            if not value:
                yield "[]"

            for item in value:
                yield (
                    json.dumps(
                        item,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )

        elif isinstance(value, dict):
            if not value:
                yield "{}"

            for key, item in value.items():
                yield (
                    json.dumps(
                        {key: item},
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )

        else:
            yield json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
