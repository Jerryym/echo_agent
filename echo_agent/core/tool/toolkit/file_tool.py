from pathlib import Path

from langchain_core.tools import BaseTool, tool


def create_read_file_tool(allowed_directories: list[str]) -> BaseTool:
    """创建读文件工具"""
    directories = [
        Path(directory).expanduser().resolve()
        for directory in allowed_directories
    ]

    @tool
    def read_file(path: str) -> str:
        """
        Read the content of a file.

        Use this tool when the current task requires reading content
        from a file within the allowed directories.

        Args:
            path: File path to read

        Returns:
            The file content
        """
        file_path = _resolve_path(path, directories)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise IsADirectoryError(f"Path is not a file: {file_path}")

        try:
            return file_path.read_text()
        except UnicodeDecodeError as exc:
            raise ValueError(f"Unable to decode file as text: {file_path}") from exc
        except OSError as exc:
            raise OSError(f"Failed to read file: {file_path}") from exc

    # 设置annotations
    read_file.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return read_file


def create_write_file_tool(allowed_directories: list[str]) -> BaseTool:
    """创建写文件工具"""
    directories = [
        Path(directory).expanduser().resolve()
        for directory in allowed_directories
    ]

    @tool
    def write_file(path: str, content: str) -> str:
        """
        Write content to a file.

        Use this tool when the current task requires creating or updating
        a file within the allowed directories.

        Args:
            path: File path to write.
            content: Content to write to the file.

        Returns:
            A message indicating that the file was written successfully.
        """
        file_path = _resolve_path(path, directories)

        if file_path.exists() and not file_path.is_file():
            raise IsADirectoryError(f"Path is not a file: {file_path}")

        try:
            file_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Failed to write file: {file_path}") from exc
        return f"File written successfully: {file_path}"

    # 设置annotations
    write_file.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return write_file


def _resolve_path(path: str, allowed_directories: list[Path]) -> Path:
    """解析并校验文件路径"""
    file_path = Path(path).expanduser().resolve()

    for allowed_directory in allowed_directories:
        try:
            file_path.relative_to(allowed_directory)
            return file_path
        except ValueError:
            continue

    raise PermissionError(f"Path is outside allowed directories: {file_path}")