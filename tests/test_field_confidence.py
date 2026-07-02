def test_field_confidence_scores_conflict_lower_and_consensus_higher():
    from field_confidence import calculate_field_confidence

    rows = [{"类型": "门诊", "报销比例": "80%"}]
    evidence = [
        {"field": "报销比例", "value": "80%", "source": "table", "evidence": "表格", "table_index": 1, "row_index": 2, "col_index": 3},
        {"field": "报销比例", "value": "80%", "source": "llm", "evidence": "原文80%"},
        {"field": "类型", "value": "门诊", "source": "llm", "evidence": ""},
    ]
    conflicts = [{"field": "类型", "reason": "conflict"}]

    scores = calculate_field_confidence(rows, evidence, conflicts)
    by_field = {item["field"]: item for item in scores}

    assert by_field["报销比例"]["confidence"] > by_field["类型"]["confidence"]
    assert by_field["报销比例"]["evidence_count"] == 2
    assert by_field["类型"]["conflict_count"] == 1


def test_review_items_include_low_confidence_and_conflicts():
    from field_confidence import build_review_rows

    rows = [{"类型": "", "报销比例": "80%"}]
    confidence = [
        {"row_index": 1, "field": "类型", "value": "", "confidence": 0.4, "reason": "核心字段缺失", "evidence": ""},
        {"row_index": 1, "field": "报销比例", "value": "80%", "confidence": 0.95, "reason": "", "evidence": "表格"},
    ]
    conflicts = [{"row_index": 1, "field": "报销比例", "reason": "冲突"}]

    review = build_review_rows(rows, confidence, conflicts, collection_logs=[{"title": "T", "source_url": "U"}])

    assert any(item["field"] == "类型" and item["suggested_action"] == "补充或确认字段" for item in review)
    assert any(item["field"] == "报销比例" and "冲突" in item["reason"] for item in review)
