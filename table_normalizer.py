import re
from dataclasses import dataclass, field
from typing import Any, List

from bs4 import BeautifulSoup


@dataclass
class NormalizedCell:
    text: str
    row_index: int
    col_index: int
    source_row: int
    source_col: int
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    header_path: List[str] = field(default_factory=list)
    raw_html: str = ""


@dataclass
class NormalizedTable:
    table_index: int
    caption: str = ""
    headers: List[str] = field(default_factory=list)
    header_paths: List[List[str]] = field(default_factory=list)
    rows: List[List[NormalizedCell]] = field(default_factory=list)
    all_rows: List[List[NormalizedCell]] = field(default_factory=list)
    markdown: str = ""


def _to_int(value: Any, default: int = 1) -> int:
    try:
        number = int(str(value or "").strip())
    except Exception:
        return default
    return max(1, number)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _cell_text(cell) -> str:
    soup = BeautifulSoup(str(cell), "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return _clean_text(soup.get_text(" ", strip=True))


def _make_cell(
    text: str,
    row_index: int,
    col_index: int,
    source_row: int,
    source_col: int,
    row_span: int,
    col_span: int,
    is_header: bool,
    raw_html: str,
) -> NormalizedCell:
    return NormalizedCell(
        text=text,
        row_index=row_index,
        col_index=col_index,
        source_row=source_row,
        source_col=source_col,
        row_span=row_span,
        col_span=col_span,
        is_header=is_header,
        raw_html=raw_html,
    )


def _expand_table(table) -> List[List[NormalizedCell]]:
    pending: dict[tuple[int, int], NormalizedCell] = {}
    expanded: List[List[NormalizedCell]] = []
    rows = table.find_all("tr")

    for row_index, tr in enumerate(rows, start=1):
        row: List[NormalizedCell] = []
        col_index = 1

        def fill_pending() -> None:
            nonlocal col_index
            while (row_index, col_index) in pending:
                row.append(pending.pop((row_index, col_index)))
                col_index += 1

        source_col = 0
        fill_pending()
        for tag in tr.find_all(["th", "td"], recursive=False):
            source_col += 1
            fill_pending()
            text = _cell_text(tag)
            row_span = _to_int(tag.get("rowspan"))
            col_span = _to_int(tag.get("colspan"))
            is_header = tag.name == "th"
            raw_html = str(tag)
            start_col = col_index
            for row_offset in range(row_span):
                for col_offset in range(col_span):
                    target_row = row_index + row_offset
                    target_col = start_col + col_offset
                    cell = _make_cell(
                        text=text,
                        row_index=target_row,
                        col_index=target_col,
                        source_row=row_index,
                        source_col=source_col,
                        row_span=row_span,
                        col_span=col_span,
                        is_header=is_header,
                        raw_html=raw_html,
                    )
                    if target_row == row_index:
                        row.append(cell)
                    else:
                        pending[(target_row, target_col)] = cell
            col_index = start_col + col_span

        fill_pending()
        if row:
            expanded.append(row)

    return expanded


def _header_row_count(rows: List[List[NormalizedCell]]) -> int:
    count = 0
    for row in rows:
        if any(cell.is_header for cell in row):
            count += 1
            continue
        break
    return count or (1 if rows else 0)


def _dedupe_path(parts: List[str]) -> List[str]:
    result: List[str] = []
    for part in parts:
        cleaned = _clean_text(part)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _build_header_paths(rows: List[List[NormalizedCell]], header_count: int, max_cols: int) -> List[List[str]]:
    paths: List[List[str]] = []
    for col_index in range(1, max_cols + 1):
        parts: List[str] = []
        for row in rows[:header_count]:
            cell = next((item for item in row if item.col_index == col_index), None)
            if cell and cell.text:
                parts.append(cell.text)
        paths.append(_dedupe_path(parts))
    return paths


def _normalize_data_rows(
    rows: List[List[NormalizedCell]],
    header_count: int,
    header_paths: List[List[str]],
    max_cols: int,
) -> List[List[NormalizedCell]]:
    data_rows: List[List[NormalizedCell]] = []
    for raw_row in rows[header_count:]:
        by_col = {cell.col_index: cell for cell in raw_row}
        normalized_row: List[NormalizedCell] = []
        for col_index in range(1, max_cols + 1):
            cell = by_col.get(col_index)
            if cell is None:
                cell = _make_cell("", raw_row[0].row_index, col_index, raw_row[0].row_index, col_index, 1, 1, False, "")
            copied = NormalizedCell(**{**cell.__dict__})
            if not copied.text:
                same_col_previous = data_rows[-1][col_index - 1].text if data_rows and len(data_rows[-1]) >= col_index else ""
                left_value = normalized_row[-1].text if normalized_row else ""
                copied.text = same_col_previous or left_value
            copied.header_path = list(header_paths[col_index - 1]) if col_index - 1 < len(header_paths) else []
            normalized_row.append(copied)
        if any(cell.text for cell in normalized_row):
            data_rows.append(normalized_row)
    return data_rows


def _escape_markdown(value: Any) -> str:
    text = str(value or "--")
    return text.replace("|", "\\|")


def _format_markdown_row(values: List[Any]) -> str:
    return "| " + " | ".join(_escape_markdown(value) for value in values) + " |"


def _build_markdown(headers: List[str], rows: List[List[NormalizedCell]]) -> str:
    if not headers:
        return ""
    markdown_rows = [_format_markdown_row(headers), _format_markdown_row(["---"] * len(headers))]
    markdown_rows.extend(_format_markdown_row([cell.text or "--" for cell in row]) for row in rows)
    return "\n".join(markdown_rows)


def normalize_table(table, table_index: int = 1) -> NormalizedTable:
    expanded = _expand_table(table)
    max_cols = max((len(row) for row in expanded), default=0)
    header_count = _header_row_count(expanded)
    header_paths = _build_header_paths(expanded, header_count, max_cols)
    headers = [path[-1] if path else f"column_{index}" for index, path in enumerate(header_paths, start=1)]
    data_rows = _normalize_data_rows(expanded, header_count, header_paths, max_cols)
    caption_tag = table.find("caption")
    caption = _clean_text(caption_tag.get_text(" ", strip=True)) if caption_tag else ""
    return NormalizedTable(
        table_index=table_index,
        caption=caption,
        headers=headers,
        header_paths=header_paths,
        rows=data_rows,
        all_rows=expanded,
        markdown=_build_markdown(headers, data_rows),
    )


def normalize_html_tables(html: Any) -> List[NormalizedTable]:
    if hasattr(html, "name") and getattr(html, "name", "") == "table":
        return [normalize_table(html, table_index=1)]
    soup = BeautifulSoup("" if html is None else str(html), "html.parser")
    return [normalize_table(table, table_index=index) for index, table in enumerate(soup.find_all("table"), start=1)]
