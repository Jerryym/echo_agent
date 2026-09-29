import os
from pathlib import Path
import tempfile

from ..model.tool import ToolArtifact


class ToolArtifactManager:
    """
    ToolArtifactManager: 负责将大型工具输出结果导出为临时文件
    """
    def __init__(self):
        pass

    def store(self, content: str) -> ToolArtifact:
        """保存工具输出结果为临时文件"""
        fd, raw_path = tempfile.mkstemp(prefix="tool_result_", suffix=".txt")
        path = Path(raw_path)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                fd = -1
                file.write(content)
        except Exception:
            if fd != -1:
                os.close(fd)
            path.unlink(missing_ok=True)
            raise

        return ToolArtifact(
            path=path,
            size=path.stat().st_size,
            media_type="text/plain",
        )
