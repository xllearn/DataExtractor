from row_quality import split_rows_by_quality
from utils import EXCEL_HEADERS


def test_three_way_split_keeps_main_candidate_and_low_value_evidence():
    rows = [
        {
            EXCEL_HEADERS[10]: "参保人",
            EXCEL_HEADERS[18]: "80%",
            "_table_index": 1,
            "_row_index": 2,
            "_table_type": "treatment_table",
            "_table_confidence": 0.9,
            "_headers": "人员类型 报销比例",
            "_row_text": "参保人 80%",
        },
        {
            EXCEL_HEADERS[18]: "60%",
            "_table_index": 2,
            "_row_index": 4,
            "_table_type": "unknown_table",
            "_table_confidence": 0.5,
            "_headers": "比例",
            "_row_text": "60%",
        },
        {
            EXCEL_HEADERS[18]: "70%",
            "_table_index": 3,
            "_row_index": 5,
            "_table_type": "contact_table",
            "_table_confidence": 0.88,
            "_headers": "客服电话 报销比例",
            "_row_text": "95500 70%",
        },
    ]

    split = split_rows_by_quality(
        rows,
        record={
            "_source_id": "SRC-1",
            "info_id": "INFO-1",
            "Title": "Policy title",
            "SourceURL": "https://example.test/policy",
        },
    )

    assert len(split["main_rows"]) == 1
    assert len(split["candidate_rows"]) == 1
    assert len(split["low_value_rows"]) == 1
    assert split["low_value_rows"][0]["mapped_values_json"]
    assert "70%" in split["low_value_rows"][0]["mapped_values_json"]
    assert split["candidate_rows"][0]["table_type"] == "unknown_table"
    assert {row["target_sheet"] for row in split["result_index_rows"]} == {"main", "candidate", "low_value"}
