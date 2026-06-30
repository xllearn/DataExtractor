import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine, inspect, text

from db_reader import quote_identifier, quote_table, validate_table_name
from image_data_loader import load_image_records
from security_utils import mask_database_url


BASE_COLUMNS = ["Title", "Content", "AuditTime", "areaname", "SourceURL", "insurancetypename", "info_id"]
TRACE_COLUMNS = ["source", "batch_id"]


def _create_table_if_needed(engine, table: str) -> None:
    validate_table_name(table)
    metadata = MetaData()
    schema = None
    name = table
    if "." in table:
        schema, name = table.split(".", 1)
    Table(
        name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("Title", Text),
        Column("Content", Text),
        Column("AuditTime", Text),
        Column("areaname", Text),
        Column("SourceURL", Text),
        Column("insurancetypename", Text),
        Column("info_id", Text),
        Column("source", Text),
        Column("batch_id", Text),
        schema=schema,
    )
    metadata.create_all(engine)


def _table_columns(engine, table: str) -> set[str]:
    validate_table_name(table)
    inspector = inspect(engine)
    if "." in table:
        schema, name = table.split(".", 1)
    else:
        schema, name = None, table
    return {column["name"] for column in inspector.get_columns(name, schema=schema)}


def _insert_sql(table: str, columns: List[str]) -> str:
    column_sql = ", ".join(quote_identifier(column) for column in columns)
    params_sql = ", ".join(f":{column}" for column in columns)
    return f"INSERT INTO {quote_table(table)} ({column_sql}) VALUES ({params_sql})"


def import_records_to_db(
    database_url: str,
    target_table: str,
    records: List[Dict[str, Any]],
    dry_run: bool = True,
    create_table: bool = False,
) -> Dict[str, Any]:
    if not database_url:
        raise ValueError("database_url 不能为空")
    if not records:
        raise ValueError("records 不能为空")
    validate_table_name(target_table)
    engine = create_engine(database_url)
    try:
        if create_table:
            _create_table_if_needed(engine, target_table)
        available_columns = _table_columns(engine, target_table)
        required = {"Title", "Content", "SourceURL"}
        missing_required = sorted(required - available_columns)
        if missing_required:
            raise ValueError(f"目标表缺少必要字段: {', '.join(missing_required)}")
        columns = [column for column in [*BASE_COLUMNS, *TRACE_COLUMNS] if column in available_columns]
        batch_id = str(records[0].get("_batch_id") or "")
        planned = []
        for record in records:
            row = {column: record.get(column, "") for column in columns}
            if "source" in columns:
                row["source"] = "image_import"
            if "batch_id" in columns:
                row["batch_id"] = record.get("_batch_id") or batch_id
            if "batch_id" not in columns and "Title" in row:
                row["Title"] = f"[image_import:{record.get('_batch_id') or batch_id}] {row['Title']}"
            planned.append(row)

        if dry_run:
            return {
                "dry_run": True,
                "database_url": mask_database_url(database_url),
                "target_table": target_table,
                "planned_count": len(planned),
                "inserted_count": 0,
                "columns": columns,
                "batch_id": batch_id,
                "records": [{"SourceURL": row.get("SourceURL"), "Title": row.get("Title")} for row in planned],
            }

        inserted: List[Dict[str, Any]] = []
        sql = text(_insert_sql(target_table, columns))
        with engine.begin() as connection:
            for row in planned:
                result = connection.execute(sql, row)
                inserted.append({"id": getattr(result, "lastrowid", None), "SourceURL": row.get("SourceURL"), "Title": row.get("Title")})
        return {
            "dry_run": False,
            "database_url": mask_database_url(database_url),
            "target_table": target_table,
            "planned_count": len(planned),
            "inserted_count": len(inserted),
            "columns": columns,
            "batch_id": batch_id,
            "records": inserted,
        }
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将图片解析结果安全写入数据库测试表")
    parser.add_argument("--image", required=True)
    parser.add_argument("--transcript", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--target-table", default="image_import_articles")
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--parsed-output", default="logs/image_import/parsed_image_data.json")
    parser.add_argument("--result-output", default="logs/image_import/import_result.json")
    parser.add_argument("--create-table", action="store_true")
    parser.add_argument("--execute", action="store_true", help="真正写入数据库；默认 dry-run")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_url = args.database_url or __import__("os").environ.get("DATABASE_URL", "")
    records = load_image_records(args.image, transcript_path=args.transcript or None, output_json=args.parsed_output, batch_id=args.batch_id)
    result = import_records_to_db(database_url, args.target_table, records, dry_run=not args.execute, create_table=args.create_table)
    output = Path(args.result_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
