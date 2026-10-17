import json
import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet


# 最大读取行数
_MAX_READ_ROWS = 1000
# 最大读取字符数
_MAX_READ_CHARS = 32768
# 最大行数
_EXCEL_MAX_ROWS = 1_048_576
# 最大列数
_EXCEL_MAX_COLUMNS = 16_384


def create_read_xlsx_tool() -> BaseTool:
    """创建 XLSX 读取工具"""
    @tool
    def read_xlsx(
        path: str,
        sheet_name: str | None = None,
        start_row: int = 1,
        max_rows: int = 100,
        max_chars: int = 12000,
    ) -> str:
        """
        Read a bounded range of rows from an XLSX spreadsheet.

        Omit sheet_name to list worksheet names without reading their data.
        To read rows, specify a sheet_name and use the returned next_row
        as start_row for the next call. Row numbers are 1-based.
        The character budget counts JSON-encoded row data, not tokens.
        A row larger than the budget raises an error instead of losing data.

        Args:
            path: Absolute path to an existing XLSX file.
            sheet_name: Worksheet to read; omit to list sheets only.
            start_row: First row to read (1-based).
            max_rows: Maximum number of rows to return (1–1000).
            max_chars: Maximum JSON-encoded characters in rows (1–32768).

        Returns:
            Sheet list, or rows with next_row and eof for pagination.
        """
        if start_row < 1:
            raise ValueError("start_row must be >= 1")
        if not 1 <= max_rows <= _MAX_READ_ROWS:
            raise ValueError(f"max_rows must be 1..{_MAX_READ_ROWS}")
        if not 1 <= max_chars <= _MAX_READ_CHARS:
            raise ValueError(f"max_chars must be 1..{_MAX_READ_CHARS}")

        file_path = _resolve_xlsx_file(path)
        workbook = load_workbook(file_path, read_only=True, data_only=True)
        try:
            if sheet_name is None:
                return {"path": str(file_path), "sheet_names": workbook.sheetnames}
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"Sheet not found: {sheet_name}; available sheets: {', '.join(workbook.sheetnames)}")

            worksheet = workbook[sheet_name]
            rows: list[list[str | int | float | bool | None]] = []
            encoded_chars = 2  # []
            eof = True
            # Read one extra row to distinguish a full page from EOF.
            iterator = worksheet.iter_rows(min_row=start_row, values_only=True)
            for values in iterator:
                row = [_serialize_cell(value) for value in values]
                # Count the separators between rows in the JSON representation.
                row_chars = len(json.dumps(row, ensure_ascii=False, default=str))
                if len(rows) >= max_rows or encoded_chars + row_chars + (1 if rows else 0) > max_chars:
                    if not rows and row_chars + 2 > max_chars:
                        raise ValueError(
                            f"Row {start_row} exceeds max_chars={max_chars}. "
                            "Increase max_chars (up to 32768) or reduce source row size."
                        )
                    eof = False
                    break
                encoded_chars += row_chars + (1 if rows else 0)
                rows.append(row)

            return {
                "path": str(file_path),
                "sheet_name": sheet_name,
                "start_row": start_row,
                "rows": rows,
                "next_row": start_row + len(rows),
                "eof": eof,
            }
        finally:
            workbook.close()

    read_xlsx.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return read_xlsx


def create_write_xlsx_tool() -> BaseTool:
    """创建 XLSX 写入工具"""
    @tool
    def write_xlsx(path: str, sheets: dict[str, list[list[Any]]]) -> str:
        """
        Create or replace an entire XLSX workbook.

        Use this for the initial workbook and its headers. This overwrites
        the target file. For subsequent batches use append_xlsx instead.

        Args:
            path: Absolute XLSX file path.
            sheets: Worksheet name to full row arrays mapping.

        Returns:
            Written file path and total number of rows.
        """
        if not sheets:
            raise ValueError("sheets is required")

        file_path = _resolve_xlsx_path(path)
        workbook = Workbook(write_only=True)
        total_rows = 0
        try:
            for sheet_name, rows in sheets.items():
                normalized_name = _validate_sheet_name(sheet_name)
                if len(rows) > _EXCEL_MAX_ROWS:
                    raise ValueError("XLSX worksheet row limit exceeded")
                worksheet = workbook.create_sheet(title=normalized_name)
                for row in rows:
                    _validate_row(row)
                    worksheet.append(row)
                    total_rows += 1
            _save_workbook_atomically(workbook, file_path)
        finally:
            workbook.close()
        return f"XLSX file written successfully: {file_path} (rows={total_rows})"

    write_xlsx.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return write_xlsx


def create_append_xlsx_tool() -> BaseTool:
    """创建 XLSX 追加写入工具"""
    @tool
    def append_xlsx(path: str, sheet_name: str, rows: list[list[Any]]) -> str:
        """
        Append new rows to an existing worksheet in an XLSX workbook.

        Use this after write_xlsx has created the workbook. Existing data
        and rows are preserved. Do not repeat headers in subsequent batches.
        Repeating this call repeats the rows; it is not idempotent.

        Args:
            path: Absolute path to an existing XLSX file.
            sheet_name: Name of an existing worksheet.
            rows: New rows to append, excluding existing headers.

        Returns:
            Workbook path and number of appended rows.
        """
        if not rows:
            raise ValueError("rows must not be empty")
        for row in rows:
            _validate_row(row)
        file_path = _resolve_xlsx_file(path)
        workbook = load_workbook(file_path)
        try:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(
                    f"Sheet not found: {sheet_name}; "
                    f"available sheets: {', '.join(workbook.sheetnames)}"
                )
            worksheet: Worksheet = workbook[sheet_name]
            if worksheet.max_row + len(rows) > _EXCEL_MAX_ROWS:
                raise ValueError("XLSX worksheet row limit exceeded")
            for row in rows:
                worksheet.append(row)
            _save_workbook_atomically(workbook, file_path)
        finally:
            workbook.close()
        return (f"XLSX rows appended successfully: {file_path} (sheet={sheet_name}, rows={len(rows)})")

    append_xlsx.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        }
    }
    return append_xlsx


def _resolve_xlsx_file(path: str) -> Path:
    """解析并校验 XLSX 文件路径"""
    file_path = _resolve_xlsx_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise IsADirectoryError(f"Path is not a file: {file_path}")

    return file_path


def _resolve_xlsx_path(path: str) -> Path:
    """解析 XLSX 文件路径"""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("path is required")

    file_path = Path(raw).expanduser()
    if not file_path.is_absolute():
        raise ValueError(f"path must be an absolute path: {path}")

    if file_path.suffix.lower() != ".xlsx":
        raise ValueError(f"path must be an XLSX file: {path}")

    return file_path.resolve()


def _save_workbook_atomically(workbook: Workbook, path: Path) -> None:
    """保存到目标文件旁边，然后只在成功保存后替换"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".xlsx", dir=path.parent
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        workbook.save(temp_path)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _validate_sheet_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Sheet name cannot be empty")
    if len(normalized_name) > 31:
        raise ValueError("Sheet name must not exceed 31 characters")
    if any(char in normalized_name for char in "[]:*?/\\"):
        raise ValueError("Sheet name contains invalid characters")
    return normalized_name


def _validate_row(row: list[Any]) -> None:
    if len(row) > _EXCEL_MAX_COLUMNS:
        raise ValueError("XLSX worksheet column limit exceeded")


def _serialize_cell(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)
