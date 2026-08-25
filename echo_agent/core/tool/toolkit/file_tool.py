from pathlib import Path

from langchain_core.tools import BaseTool, tool


def create_read_file_tool() -> BaseTool:
    """创建读文件工具"""

    @tool
    def read_file(path: str) -> str:
        """
        Read the content of a regular file.

        Use this tool when the current task requires reading file content.

        MUST NOT be used to read Skill definitions, instructions, or any
        other Skill-related content. Use the Skill loading mechanism instead.

        Args:
            path: Absolute file path to read.

        Returns:
            The file content.
        """
        file_path = _resolve_path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise IsADirectoryError(f"Path is not a file: {file_path}")

        try:
            return _read_text(file_path)
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


def create_write_file_tool() -> BaseTool:
    """创建写文件工具"""

    @tool
    def write_file(path: str, content: str) -> str:
        """
        Write content to a file.

        Use this tool when the current task requires creating or updating
        a file.

        Args:
            path: Absolute file path to write.
            content: Content to write to the file.

        Returns:
            A message indicating that the file was written successfully.
        """
        file_path = _resolve_path(path)

        if file_path.exists() and not file_path.is_file():
            raise IsADirectoryError(f"Path is not a file: {file_path}")

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
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


def create_edit_file_tool() -> BaseTool:
    """创建文件编辑工具"""

    @tool
    def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        """
        Edit a file by replacing text.

        Use this tool when the current task requires a targeted update
        rather than rewriting the whole file. Prefer unique old_string
        context so the intended occurrence is replaced.

        Args:
            path: Absolute file path to edit.
            old_string: Exact text to find.
            new_string: Replacement text.
            replace_all: If true, replace every occurrence. If false,
                old_string must match exactly once.

        Returns:
            A message indicating how many replacements were made.
        """
        if old_string == new_string:
            raise ValueError("old_string and new_string must be different")
        if not old_string:
            raise ValueError("old_string is required")

        file_path = _resolve_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not file_path.is_file():
            raise IsADirectoryError(f"Path is not a file: {file_path}")

        try:
            content = _read_text(file_path)
        except OSError as exc:
            raise OSError(f"Failed to read file: {file_path}") from exc

        count = content.count(old_string)
        if count == 0:
            raise ValueError(f"old_string was not found in file: {file_path}")
        if not replace_all and count > 1:
            raise ValueError(
                f"old_string matched {count} times; provide more context "
                "or set replace_all=true"
            )

        updated = content.replace(old_string, new_string) if replace_all else content.replace(
            old_string, new_string, 1
        )

        try:
            file_path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Failed to write file: {file_path}") from exc

        replaced = count if replace_all else 1
        return f"File edited successfully: {file_path} ({replaced} replacement(s))"

    edit_file.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return edit_file


_SEARCH_FILES_LIMIT = 200


def create_search_files_tool() -> BaseTool:
    """创建文件搜索工具"""

    @tool
    def search_files(path: str, pattern: str) -> str:
        """
        Search for files under a directory matching a glob pattern.

        Use this tool when the current task requires locating files by name
        or extension. Relative glob patterns are resolved from the given
        directory. Use ** for recursive matches (e.g. **/*.csv).

        Args:
            path: Absolute directory path to search under.
            pattern: Glob pattern relative to path (e.g. *.txt or **/*.csv).

        Returns:
            Matching file paths, one per line.
        """
        root = _resolve_directory(path)
        glob_pattern = (pattern or "").strip()
        if not glob_pattern:
            raise ValueError("pattern is required")

        try:
            matches: list[str] = []
            truncated = False
            for candidate in root.glob(glob_pattern):
                if not candidate.is_file():
                    continue
                matches.append(str(candidate))
                if len(matches) >= _SEARCH_FILES_LIMIT:
                    truncated = True
                    break
        except OSError as exc:
            raise OSError(f"Failed to search files: {root}") from exc

        if not matches:
            return "No files matched."
        matches.sort()
        result = "\n".join(matches)
        if truncated:
            result += f"\n(truncated to {_SEARCH_FILES_LIMIT} results)"
        return result

    search_files.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        }
    }
    return search_files


def create_list_directory_tool() -> BaseTool:
    """创建目录列举工具"""

    @tool
    def list_directory(path: str) -> str:
        """
        List the contents of a directory.

        Use this tool when the current task requires seeing files and
        subdirectories in a single directory. This listing is not recursive.

        Args:
            path: Absolute directory path to list.

        Returns:
            Directory entries, one per line, prefixed with dir or file.
        """
        dir_path = _resolve_directory(path)

        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.casefold()),
            )
        except OSError as exc:
            raise OSError(f"Failed to list directory: {dir_path}") from exc

        if not entries:
            return "(empty directory)"

        lines: list[str] = []
        for entry in entries:
            kind = "dir" if entry.is_dir() else "file"
            lines.append(f"{kind}\t{entry}")
        return "\n".join(lines)

    list_directory.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        }
    }
    return list_directory


def create_directory_tool() -> BaseTool:
    """创建目录创建工具"""

    @tool
    def create_directory(path: str) -> str:
        """
        Create a directory.

        Use this tool when the current task requires creating a folder.
        Missing parent directories are created as well. If the directory
        already exists, this is a no-op.

        Args:
            path: Absolute directory path to create.

        Returns:
            A message indicating that the directory was created.
        """
        dir_path = _resolve_path(path)
        if dir_path.exists() and not dir_path.is_dir():
            raise NotADirectoryError(f"Path exists and is not a directory: {dir_path}")

        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(f"Failed to create directory: {dir_path}") from exc
        return f"Directory created successfully: {dir_path}"

    create_directory.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return create_directory


def _read_text(file_path: Path) -> str:
    data = file_path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _resolve_path(path: str) -> Path:
    """解析路径；仅接受绝对路径。"""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("path is required")
    file_path = Path(raw).expanduser()
    if not file_path.is_absolute():
        raise ValueError(f"path must be an absolute path: {path}")
    return file_path.resolve()


def _resolve_directory(path: str) -> Path:
    """解析并校验目录路径。"""
    dir_path = _resolve_path(path)
    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {dir_path}")
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {dir_path}")
    return dir_path
