from datetime import datetime
from pathlib import Path
from copy import copy
from typing import Dict, Iterable, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from utils import EXCEL_HEADERS, build_single_filename, ensure_dir


LONG_TEXT_HEADERS = {"个人账户计入办法", "个人账户使用范围", "备注", "相关资讯"}


def write_rows_to_workbook(rows: Iterable[Dict[str, object]], output_path: Path, template_path: Path) -> Path:
    output_path = Path(output_path)
    ensure_dir(output_path.parent)

    if template_path.exists():
        workbook = load_workbook(template_path)
        worksheet = workbook.active
    else:
        workbook = Workbook()
        worksheet = workbook.active

    ensure_headers(worksheet)
    append_rows(worksheet, rows)
    format_worksheet(worksheet)
    workbook.save(output_path)
    return output_path


def ensure_headers(worksheet) -> None:
    for index, header in enumerate(EXCEL_HEADERS, start=1):
        cell = worksheet.cell(row=1, column=index)
        cell.value = header
        if cell.font:
            font = copy(cell.font)
            font.bold = True
            cell.font = font
        else:
            cell.font = Font(bold=True)
        if cell.fill is None or cell.fill.fill_type is None:
            cell.fill = PatternFill("solid", fgColor="D9EAF7")


def append_rows(worksheet, rows: Iterable[Dict[str, object]]) -> None:
    for row in rows:
        worksheet.append([row.get(header, "--") for header in EXCEL_HEADERS])


def format_worksheet(worksheet) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:{get_column_letter(len(EXCEL_HEADERS))}{worksheet.max_row}"

    for column_index, header in enumerate(EXCEL_HEADERS, start=1):
        letter = get_column_letter(column_index)
        max_length = len(header)
        for cell in worksheet[letter]:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, min(len(value), 60))
            if header in LONG_TEXT_HEADERS or len(value) > 30:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            else:
                cell.alignment = Alignment(vertical="top")
        worksheet.column_dimensions[letter].width = min(max(max_length + 2, 10), 45)


def build_single_output_path(record: Dict[str, object], output_dir: Path, sequence: int) -> Path:
    return Path(output_dir) / build_single_filename(record, sequence)


def build_merge_output_path(output_dir: Path) -> Path:
    filename = f"商业补充保险抽取结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Path(output_dir) / filename
