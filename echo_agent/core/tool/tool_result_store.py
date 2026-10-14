import os
from pathlib import Path
import tempfile

from ..model.tool import ToolResult, ToolResultItem


class ToolResultStore:
    """
    工具执行结果存储管理器:  统一管理 ToolResult，根据序列化后的数据大小，决定将结果保留在内存中或卸载到临时 JSON 文件
    """
    # 默认阈值
    DEFAULT_THRESHOLD = 128 * 1024

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        if threshold < 0:
            raise ValueError("threshold must be non-negative")

        self._threshold = threshold

    def put(self, result: ToolResult) -> ToolResultItem:
        """将工具执行结果存储为 ToolResultItem"""
        content = result.model_dump_json().encode("utf-8")

        if len(content) <= self._threshold:
            return ToolResultItem(
                tool_call_id=result.tool_call_id,
                name=result.name,
                success=result.success,
                error=result.error,
                storage="memory",
                result=result.result,
            )

        fd, temp_name = tempfile.mkstemp(
            prefix="tool_result_",
            suffix=".tmp",
        )

        temp_path = Path(temp_name)
        file_path = temp_path.with_suffix(".json")

        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)

            os.replace(temp_path, file_path)
            return ToolResultItem(
                tool_call_id=result.tool_call_id,
                name=result.name,
                success=result.success,
                error=result.error,
                storage="file",
                path=file_path,
            )

        except BaseException:
            temp_path.unlink(missing_ok=True)
            file_path.unlink(missing_ok=True)
            raise

    def get(self, result_item: ToolResultItem) -> ToolResult:
        """从 ToolResultItem 中恢复工具执行结果"""
        if result_item.storage == "memory":
            return ToolResult(
                tool_call_id=result_item.tool_call_id,
                name=result_item.name,
                success=result_item.success,
                error=result_item.error,
                result=result_item.result,
            )

        if result_item.path is None:
            raise ValueError("File storage requires a path")

        result = ToolResult.model_validate_json(result_item.path.read_bytes())
        if result.tool_call_id != result_item.tool_call_id:
            raise ValueError("Stored ToolResult tool_call_id mismatch")

        return result
