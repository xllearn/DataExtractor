import re
from typing import Any, Dict, List

import pymysql

from config import Settings


DANGEROUS_SQL_KEYWORDS = {
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "GRANT",
    "REVOKE",
}


def validate_where_clause(where: str) -> str:
    where = (where or "").strip()
    if not where:
        return ""
    tokens = {token.upper() for token in re.findall(r"[A-Za-z_]+", where)}
    blocked = tokens & DANGEROUS_SQL_KEYWORDS
    if blocked:
        raise ValueError(f"--where 包含禁止关键词: {', '.join(sorted(blocked))}")
    if ";" in where or "--" in where or "/*" in where or "*/" in where:
        raise ValueError("--where 包含不允许的 SQL 注释或分号")
    return where


def fetch_records(settings: Settings, limit: int, offset: int, where: str = "") -> List[Dict[str, Any]]:
    if not settings.db_name or not settings.db_table:
        raise ValueError("请在 .env 中配置 DB_NAME 和 DB_TABLE")

    validated_where = validate_where_clause(where)
    table_name = settings.db_table.replace("`", "``")
    where_clause = f"WHERE {validated_where}" if validated_where else ""
    sql = f"""
SELECT
  Title,
  Source,
  SourceURL,
  AuditTime,
  SourceAreaID,
  areaname,
  Content,
  province,
  insurancetypename
FROM `{table_name}`
{where_clause}
ORDER BY AuditTime DESC, SourceURL ASC
LIMIT %s OFFSET %s;
""".strip()

    connection = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, (limit, offset))
            return list(cursor.fetchall())
    finally:
        connection.close()
