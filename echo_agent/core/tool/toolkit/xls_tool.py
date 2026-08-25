from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
import xlrd
import xlwt


def create_read_xls_tool() -> BaseTool:
    """创建 XLS 读取工具"""

    @tool
    def read_xls(path: str, sheet_name: str | None = None) -> str:
        """
        Read data from an XLS file.

        Use this tool when the current task requires reading spreadsheet
        content from an XLS file.

        If sheet_name is omitted, all sheets are read. If sheet_name is
        provided, only the specified sheet is read.

        Args:
            path: Absolute XLS file path.
            sheet_name: Optional sheet name to read.

        Returns:
            Spreadsheet data grouped by sheet.
        """
        file_path = _resolve_xls_file(path)

        try:
            workbook = xlrd.open_workbook(
                filename=str(file_path),
                on_demand=True,
            )
        except (OSError, xlrd.XLRDError) as exc:
            raise OSError(f"Failed to read XLS file: {file_path}") from exc

        try:
            if sheet_name is not None:
                if sheet_name not in workbook.sheet_names():
                    raise ValueError(
                        f"Sheet not found: {sheet_name}; "
                        f"available sheets: {', '.join(workbook.sheet_names())}"
                    )

                sheet_names = [sheet_name]
            else:
                sheet_names = workbook.sheet_names()

            result: list[str] = []

            for name in sheet_names:
                worksheet = workbook.sheet_by_name(name)

                result.append(f"## Sheet: {name}")

                for row_index in range(worksheet.nrows):
                    values = [
                        _format_cell(worksheet.cell_value(row_index, column_index))
                        for column_index in range(worksheet.ncols)
                    ]
                    result.append("\t".join(values))

            return "\n".join(result)
        finally:
            workbook.release_resources()

    read_xls.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return read_xls


def create_write_xls_tool() -> BaseTool:
    """创建 XLS 写入工具"""

    @tool
    def write_xls(path: str, sheets: dict[str, list[list[Any]]]) -> str:
        """
        Write data to an XLS file.

        Use this tool when the current task requires creating or replacing
        an XLS spreadsheet.

        Multiple sheets can be written in a single operation.

        Args:
            path: Absolute XLS file path.
            sheets: Mapping of sheet names to row data. Each row is a list
                of cell values.

        Returns:
            A message indicating that the XLS file was written successfully.
        """
        if not sheets:
            raise ValueError("sheets is required")

        file_path = _resolve_xls_path(path)

        workbook = xlwt.Workbook()

        try:
            for sheet_name, rows in sheets.items():
                normalized_name = sheet_name.strip()

                if not normalized_name:
                    raise ValueError("Sheet name cannot be empty")

                worksheet = workbook.add_sheet(normalized_name)

                for row_index, row in enumerate(rows):
                    for column_index, value in enumerate(row):
                        worksheet.write(row_index, column_index, value)

            try:
                workbook.save(str(file_path))
            except OSError as exc:
                raise OSError(
                    f"Failed to write XLS file: {file_path}"
                ) from exc
        finally:
            del workbook

        return (
            f"XLS file written successfully: {file_path} "
            f"({len(sheets)} sheet(s))"
        )

    write_xls.metadata = {
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return write_xls


def _resolve_xls_file(path: str) -> Path:
    """解析并校验 XLS 文件路径。"""
    file_path = _resolve_xls_path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise IsADirectoryError(f"Path is not a file: {file_path}")

    return file_path


def _resolve_xls_path(path: str) -> Path:
    """解析 XLS 文件路径。"""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("path is required")

    file_path = Path(raw).expanduser()

    if not file_path.is_absolute():
        raise ValueError(f"path must be an absolute path: {path}")

    if file_path.suffix.lower() != ".xls":
        raise ValueError(f"path must be an XLS file: {path}")

    return file_path.resolve()


def _format_cell(value: Any) -> str:
    """将单元格值转换为文本。"""
    if value is None:
        return ""

    return str(value)
