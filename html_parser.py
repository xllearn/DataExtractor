from dataclasses import dataclass, field
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from table_normalizer import NormalizedTable, normalize_table


@dataclass
class ParsedHtml:
    clean_text: str
    tables_text: str
    image_urls: List[str]
    normalized_tables: List[NormalizedTable] = field(default_factory=list)


def parse_html_content(html: object, image_base_url: str = "", logger: Optional[logging.Logger] = None) -> ParsedHtml:
    html_text = "" if html is None else str(html)
    soup = BeautifulSoup(html_text, "lxml")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    image_urls = _extract_image_urls(soup, image_base_url, logger)
    normalized_tables = [normalize_table(table, table_index=index) for index, table in enumerate(soup.find_all("table"), start=1)]
    tables_text = "\n\n".join(table.markdown for table in normalized_tables if table.markdown)
    clean_text = _extract_clean_text(soup)

    return ParsedHtml(clean_text=clean_text, tables_text=tables_text, image_urls=image_urls, normalized_tables=normalized_tables)


def _extract_clean_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["br"]):
        tag.replace_with("\n")
    text = soup.get_text("\n")
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _table_to_markdown(table) -> str:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        rows.append([cell.get_text(" ", strip=True) or "--" for cell in cells])
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * max_cols
    body = normalized[1:]

    markdown_rows = [_format_markdown_row(header), _format_markdown_row(separator)]
    markdown_rows.extend(_format_markdown_row(row) for row in body)
    return "\n".join(markdown_rows)


def _format_markdown_row(row: List[str]) -> str:
    escaped = [str(cell).replace("|", "\\|") for cell in row]
    return "| " + " | ".join(escaped) + " |"


def _extract_image_urls(soup: BeautifulSoup, image_base_url: str, logger: Optional[logging.Logger]) -> List[str]:
    urls: List[str] = []
    for img in soup.find_all("img"):
        raw = img.get("data-src") or img.get("src") or img.get("data-original")
        normalized = normalize_image_url(raw, image_base_url, logger)
        if normalized:
            urls.append(normalized)
    return urls


def normalize_image_url(raw_url: object, image_base_url: str = "", logger: Optional[logging.Logger] = None) -> Optional[str]:
    if raw_url is None:
        return None
    url = str(raw_url).strip()
    if not url:
        return None
    if url.startswith("https://") or url.startswith("http://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if not image_base_url:
        if logger:
            logger.warning("跳过相对路径图片，IMAGE_BASE_URL 为空: %s", url)
        return None
    base = image_base_url.strip()
    if not base:
        return None
    if url.startswith("/"):
        return urljoin(base.rstrip("/") + "/", url)
    return urljoin(base.rstrip("/") + "/", url)
