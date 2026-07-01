import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

from config_loader import DbConfig


class DbReaderError(RuntimeError):
    pass


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]+$")
TABLE_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]+(?:\.[A-Za-z0-9_\u4e00-\u9fff]+)?$")
SEARCH_SOURCE_FIELDS = [
    "title_column",
    "html_column",
    "text_column",
    "info_id_column",
    "region_column",
    "source_url_column",
    "related_info_column",
]


@dataclass
class BuiltQuery:
    statement: str
    params: Dict[str, Any]


def validate_identifier(value: str, label: str = "字段名") -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not IDENTIFIER_RE.fullmatch(value):
        raise DbReaderError(f"{label} 只允许中文、英文字母、数字或下划线: {value}")
    return value


def validate_column_name(value: str, label: str = "字段名") -> str:
    return validate_identifier(value, label)


def validate_table_name(value: str) -> str:
    value = (value or "").strip()
    if not TABLE_RE.fullmatch(value):
        raise DbReaderError(f"source.table 只允许中文、英文字母、数字、下划线或单个 schema.table 分隔点: {value}")
    return value


def quote_identifier(value: str) -> str:
    validate_identifier(value)
    return f"`{value}`"


def quote_table(value: str) -> str:
    validate_table_name(value)
    return ".".join(f"`{part}`" for part in value.split("."))


def _configured_columns(config: DbConfig) -> List[str]:
    columns: List[str] = []
    source = config.source
    for field_name in source.__dataclass_fields__:
        if field_name == "table":
            continue
        column = validate_identifier(getattr(source, field_name), f"source.{field_name}")
        if column and column not in columns:
            columns.append(column)
    for header, column in config.direct_field_columns.items():
        column = validate_identifier(column, f"direct_field_columns.{header}")
        if column and column not in columns:
            columns.append(column)
    if not columns:
        raise DbReaderError("配置中没有可读取的字段")
    return columns


def _search_columns(config: DbConfig) -> List[str]:
    columns: List[str] = []
    for field_name in SEARCH_SOURCE_FIELDS:
        column = validate_identifier(getattr(config.source, field_name), f"source.{field_name}")
        if column and column not in columns:
            columns.append(column)
    return columns


def _selected_ids_clause(config: DbConfig, selected_ids: Sequence[str], params: Dict[str, Any]) -> str:
    candidate_columns = [
        validate_identifier(config.source.id_column, "source.id_column"),
        validate_identifier(config.source.info_id_column, "source.info_id_column"),
    ]
    candidate_columns = [column for column in candidate_columns if column]
    if not candidate_columns:
        raise DbReaderError("使用 --selected-ids 时需要配置 source.id_column 或 source.info_id_column")

    placeholders = []
    for index, selected_id in enumerate(selected_ids):
        name = f"selected_id_{index}"
        params[name] = selected_id
        placeholders.append(f":{name}")
    in_expr = ", ".join(placeholders)
    return "(" + " OR ".join(f"{quote_identifier(column)} IN ({in_expr})" for column in candidate_columns) + ")"


def _keyword_clause(config: DbConfig, keyword_groups: Sequence[Sequence[str]], keyword_mode: str, params: Dict[str, Any]) -> str:
    search_columns = _search_columns(config)
    if not search_columns:
        raise DbReaderError("关键词检索需要至少配置一个可搜索字段")

    group_clauses: List[str] = []
    for group_index, group in enumerate(keyword_groups):
        term_clauses: List[str] = []
        for term_index, term in enumerate(group):
            param_name = f"kw_{group_index}_{term_index}"
            params[param_name] = f"%{term}%"
            for column in search_columns:
                term_clauses.append(f"{quote_identifier(column)} LIKE :{param_name}")
        if term_clauses:
            group_clauses.append("(" + " OR ".join(term_clauses) + ")")
    if not group_clauses:
        return ""
    joiner = " AND " if keyword_mode == "and" else " OR "
    return "(" + joiner.join(group_clauses) + ")"


def _query_filters(
    config: DbConfig,
    selected_ids: Sequence[str] | None,
    keyword_groups: Sequence[Sequence[str]] | None,
    keyword_mode: str,
    params: Dict[str, Any],
) -> List[str]:
    where_parts: List[str] = []
    selected_ids = list(selected_ids or [])
    keyword_groups = list(keyword_groups or [])
    if selected_ids:
        where_parts.append(_selected_ids_clause(config, selected_ids, params))
    elif keyword_groups:
        where_parts.append(_keyword_clause(config, keyword_groups, keyword_mode, params))
    return where_parts


def build_article_query(
    config: DbConfig,
    limit: int,
    offset: int,
    selected_ids: Sequence[str] | None = None,
    keyword_groups: Sequence[Sequence[str]] | None = None,
    keyword_mode: str = "or",
) -> BuiltQuery:
    table = quote_table(config.source.table)
    columns = _configured_columns(config)
    params: Dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
    where_parts = _query_filters(config, selected_ids, keyword_groups, keyword_mode, params)

    order_columns = [
        validate_identifier(config.source.audit_time_column, "source.audit_time_column"),
        validate_identifier(config.source.source_url_column, "source.source_url_column"),
    ]
    order_exprs = [f"{quote_identifier(column)} DESC" if index == 0 else f"{quote_identifier(column)} ASC" for index, column in enumerate(order_columns) if column]

    sql = f"SELECT {', '.join(quote_identifier(column) for column in columns)} FROM {table}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if order_exprs:
        sql += " ORDER BY " + ", ".join(order_exprs)
    sql += " LIMIT :limit OFFSET :offset"
    return BuiltQuery(statement=sql, params=params)


def build_article_count_query(
    config: DbConfig,
    selected_ids: Sequence[str] | None = None,
    keyword_groups: Sequence[Sequence[str]] | None = None,
    keyword_mode: str = "or",
) -> BuiltQuery:
    table = quote_table(config.source.table)
    params: Dict[str, Any] = {}
    where_parts = _query_filters(config, selected_ids, keyword_groups, keyword_mode, params)
    sql = f"SELECT COUNT(*) AS total FROM {table}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    return BuiltQuery(statement=sql, params=params)


def _first_value(row: Dict[str, Any], columns: Iterable[str]) -> Any:
    for column in columns:
        if column and row.get(column) is not None:
            return row.get(column)
    return None


def map_row_to_record(row: Dict[str, Any], config: DbConfig) -> Dict[str, Any]:
    source = config.source
    content = _first_value(row, [source.html_column, source.text_column])
    region = row.get(source.region_column) if source.region_column else None
    record = {
        "Title": row.get(source.title_column) if source.title_column else None,
        "Source": row.get("Source"),
        "SourceURL": row.get(source.source_url_column) if source.source_url_column else None,
        "AuditTime": row.get(source.audit_time_column) if source.audit_time_column else None,
        "SourceAreaID": None,
        "areaname": region,
        "Content": content,
        "province": region,
        "insurancetypename": row.get(source.insurance_type_column) if source.insurance_type_column else None,
        "info_id": row.get(source.info_id_column) if source.info_id_column else None,
        "_source_id": row.get(source.id_column) if source.id_column else None,
        "_direct_fields": {},
    }
    for header, column in config.direct_field_columns.items():
        if column:
            record["_direct_fields"][header] = row.get(column)
    return record


def fetch_configured_records(
    config: DbConfig,
    limit: int,
    offset: int,
    selected_ids: Sequence[str] | None = None,
    keyword_groups: Sequence[Sequence[str]] | None = None,
    keyword_mode: str = "or",
) -> List[Dict[str, Any]]:
    try:
        from sqlalchemy import create_engine, text
    except Exception as exc:  # pragma: no cover - dependency guard
        raise DbReaderError("缺少 SQLAlchemy 依赖，请运行 pip install -r requirements.txt") from exc

    query = build_article_query(config, limit, offset, selected_ids, keyword_groups, keyword_mode)
    try:
        engine = create_engine(config.database_url)
        with engine.connect() as connection:
            rows = connection.execute(text(query.statement), query.params).mappings().all()
        return [map_row_to_record(dict(row), config) for row in rows]
    except Exception as exc:
        raise DbReaderError(f"配置化数据库读取失败: {exc}") from exc


def count_configured_records(
    config: DbConfig,
    selected_ids: Sequence[str] | None = None,
    keyword_groups: Sequence[Sequence[str]] | None = None,
    keyword_mode: str = "or",
) -> int:
    try:
        from sqlalchemy import create_engine, text
    except Exception as exc:  # pragma: no cover - dependency guard
        raise DbReaderError("缺少 SQLAlchemy 依赖，请运行 pip install -r requirements.txt") from exc

    query = build_article_count_query(config, selected_ids, keyword_groups, keyword_mode)
    try:
        engine = create_engine(config.database_url)
        with engine.connect() as connection:
            value = connection.execute(text(query.statement), query.params).scalar()
        return int(value or 0)
    except Exception as exc:
        raise DbReaderError(f"配置化数据库 count 失败: {exc}") from exc
