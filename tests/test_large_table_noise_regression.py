from row_quality import build_row_quality_summary, split_rows_by_quality
from utils import EXCEL_HEADERS


def test_large_noise_table_no_longer_creates_500_plus_main_rows_with_zero_useful_rows():
    rows = [
        {
            EXCEL_HEADERS[18]: f"{index % 100}%",
            "_table_index": 1,
            "_row_index": index,
            "_table_type": "co_insurer_table",
            "_table_confidence": 0.93,
            "_headers": "保险公司 服务电话 比例",
            "_row_text": f"示例保险公司 {index} 95500 {index % 100}%",
        }
        for index in range(1, 601)
    ]
    record = {
        "_source_id": "SRC-LARGE",
        "info_id": "INFO-LARGE",
        "Title": "large co-insurer table",
        "SourceURL": "https://example.test/large",
    }

    split = split_rows_by_quality(rows, record=record)
    metadata = {**split, "review_rows": []}
    summary = build_row_quality_summary(metadata)

    assert len(split["main_rows"]) == 0
    assert len(split["low_value_rows"]) == 600
    assert summary["main_result_rows"] == 0
    assert summary["useful_main_rows"] == 0
    assert summary["low_value_table_rows"] == 600
    assert summary["top_noisy_records"][0]["low_value_rows"] == 600
