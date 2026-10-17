from pathlib import Path
from typing import TextIO

from langchain_core.tools import BaseTool, tool


# 默认读取最大行数
_DEFAULT_READ_MAX_LINES = 200
# 默认读取最大字符数
_DEFAULT_READ_MAX_CHARS = 12000
# 最大读取行数
_MAX_READ_LINES = 2000
# 最大读取字符数
_MAX_READ_CHARS = 32768
# 读取缓冲区大小
_READ_BUFFER_SIZE = 4096
# 搜索文件最大数量
_SEARCH_FILES_LIMIT = 200


def create_read_file_tool() -> BaseTool:
    """创建读文件工具"""
    @tool
    def read_file(
        path: str, 
        start_line: int = 1, 
        start_column: int = 0, 
        max_lines: int = _DEFAULT_READ_MAX_LINES, 
        max_chars: int = _DEFAULT_READ_MAX_CHARS, 
        encoding: str = "utf-8-sig",
    ) -> dict[str, str | int | bool]:
        """
        Read a bounded portion of a regular text file.

        Use the returned next_line and next_column for exact continuation.
        Lines are 1-based; columns are 0-based decoded character offsets.
        This tool MUST NOT read Skill definitions or other Skill content;
        use the Skill loading mechanism instead.

        Args:
            path: Absolute file path.
            start_line: First line to read (1-based).
            start_column: Character offset inside start_line (0-based).
            max_lines: Maximum number of logical lines to visit (1..2000).
            max_chars: Maximum returned characters (1..32768).
            encoding: Text encoding (default UTF-8 with optional BOM).

        Returns:
            Content, current cursor, next cursor, and EOF flag.
        """
        if start_line < 1 or start_column < 0:
            raise ValueError("start_line must be >= 1 and start_column must be >= 0")
        if not 1 <= max_lines <= _MAX_READ_LINES:
            raise ValueError(f"max_lines must be between 1 and {_MAX_READ_LINES}")
        if not 1 <= max_chars <= _MAX_READ_CHARS:
            raise ValueError(f"max_chars must be between 1 and {_MAX_READ_CHARS}")
        if not encoding.strip():
            raise ValueError("encoding is required")

        file_path = _resolve_file(path)
        try:
            with file_path.open("r", encoding=encoding, errors="strict", newline="") as stream:
                reached = _skip_lines(stream, start_line - 1)
                if not reached:
                    if start_column:
                        raise ValueError("start_column must be 0 beyond EOF")
                    return {
                        "content": "", "start_line": start_line,
                        "start_column": start_column, "next_line": start_line,
                        "next_column": 0, "eof": True,
                    }
                _skip_columns(stream, start_column)
                remaining = max_chars
                current_line = start_line
                current_column = start_column
                pieces: list[str] = []

                for _ in range(max_lines):
                    if remaining == 0:
                        break
                    piece = stream.readline(remaining)
                    if not piece:
                        break
                    pieces.append(piece)
                    remaining -= len(piece)
                    if piece.endswith("\n") or piece.endswith("\r"):
                        current_line += 1
                        current_column = 0
                    else:
                        current_column += len(piece)
                        # A bounded readline may have stopped inside a line.
                        if remaining == 0:
                            break
                        # No line terminator means EOF (readline otherwise
                        # returns at a newline), so stop reading.
                        break

                position = stream.tell()
                eof = stream.read(1) == ""
                stream.seek(position)
                return {
                    "content": "".join(pieces),
                    "start_line": start_line,
                    "start_column": start_column,
                    "next_line": current_line,
                    "next_column": current_column,
                    "eof": eof,
                }
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

        Use this tool when the current task requires creating or replacing
        the entire content of a file. For adding content to an existing
        file, use append_file instead.

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


def create_append_file_tool() -> BaseTool:
    """创建文件追加工具"""
    @tool
    def append_file(path: str, content: str, encoding: str = "utf-8") -> str:
        """
        Append text to the end of an existing regular file.

        The content is appended verbatim; no newline is inserted.
        Call write_file first to create a missing file. Repeated calls
        append duplicate content, so avoid blind retries.

        Args:
            path: Absolute path to an existing file.
            content: Text to append.
            encoding: Existing file encoding (default UTF-8).

        Returns:
            A message with appended character count.
        """
        if not encoding.strip():
            raise ValueError("encoding is required")
        file_path = _resolve_file(path)
        try:
            with file_path.open("a", encoding=encoding, errors="strict", newline="") as stream:
                stream.write(content)
        except OSError as exc:
            raise OSError(f"Failed to append file: {file_path}") from exc
        return f"File appended successfully: {file_path} ({len(content)} character(s))"

    # 设置annotations
    append_file.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        }
    }
    return append_file


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
            raise ValueError(f"old_string matched {count} times; provide more context or set replace_all=true")

        updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

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


def _resolve_file(path: str) -> Path:
    """解析并校验已存在的文件"""
    file_path = _resolve_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise IsADirectoryError(f"Path is not a file: {file_path}")
    return file_path


def _resolve_path(path: str) -> Path:
    """解析路径；仅接受绝对路径"""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("path is required")
    file_path = Path(raw).expanduser()
    if not file_path.is_absolute():
        raise ValueError(f"path must be an absolute path: {path}")
    return file_path.resolve()


def _resolve_directory(path: str) -> Path:
    """解析并校验目录路径"""
    dir_path = _resolve_path(path)
    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {dir_path}")
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {dir_path}")
    return dir_path


def _skip_lines(stream: TextIO, count: int) -> bool:
    """跳过 count 个完整逻辑行；到达 EOF 时返回 False"""
    for _ in range(count):
        while True:
            piece = stream.readline(_READ_BUFFER_SIZE)
            if not piece:
                return False
            if piece.endswith("\n") or piece.endswith("\r"):
                break
    return True


def _skip_columns(stream: TextIO, count: int) -> None:
    """在当前行内跳过 count 个字符，不允许越过行尾"""
    remaining = count
    while remaining:
        chunk = stream.readline(min(remaining, _READ_BUFFER_SIZE))
        if not chunk or "\n" in chunk or "\r" in chunk:
            raise ValueError("start_column exceeds the length of the requested line")
        remaining -= len(chunk)
