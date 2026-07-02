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
    assert by_field["报销比例"]["review_status"] == "pending"


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
    assert all(item["review_status"] == "pending" for item in review)
    assert any(item["field"] == "类型" and item["current_value"] == "" for item in review)


def test_collection_failures_and_weak_row_match_lower_confidence_and_create_review_rows():
    from field_confidence import build_review_rows, calculate_field_confidence

    rows = [{"类型": "门诊", "报销比例": "80%"}]
    evidence = [
        {
            "field": "报销比例",
            "value": "80%",
            "source": "table",
            "evidence": "表格显示报销比例80%",
            "table_index": 1,
            "col_index": 3,
            "evidence_id": "T1",
            "attempt": "ocr_retry",
        },
        {
            "field": "报销比例",
            "value": "80%",
            "source": "llm",
            "evidence": "报销比例80%",
            "evidence_id": "L1",
            "attempt": "ocr_retry",
        },
    ]
    row_match_evidence = [
        {
            "attempt": "ocr_retry",
            "row_a": 1,
            "row_b": 1,
            "match_level": "weak",
            "needs_review": True,
            "reason": "matched",
        }
    ]
    collection_logs = [
        {
            "source_id": "S1",
            "info_id": "I1",
            "title": "测试标题",
            "source_url": "https://example.test",
            "attempt": "ocr_retry",
            "final_attempt": "ocr_retry",
            "ocr_failure_count": 1,
            "ocr_failure_reason": "timeout",
            "llm_parse_success": False,
            "initial_confidence_score": 82,
            "ocr_retry_confidence_score": 75,
            "review_reason": "规则记录和 LLM 记录数量不一致，需要人工复核",
        }
    ]

    confidence_rows = calculate_field_confidence(
        rows,
        evidence,
        [],
        collection_logs=collection_logs,
        row_match_evidence=row_match_evidence,
        source_text="报销比例80%",
        table_text="表格显示报销比例80%",
    )
    target = next(item for item in confidence_rows if item["field"] == "报销比例")

    assert target["confidence"] < 0.7
    assert target["match_level"] == "weak"
    assert target["needs_review"] is True
    assert target["attempt"] == "ocr_retry"
    assert target["review_status"] == "pending"
    for reason in ["OCR failed", "LLM parse failed", "OCR retry confidence down", "row count mismatch", "weak row match"]:
        assert reason in target["reason"]

    review_rows = build_review_rows(
        rows,
        confidence_rows,
        [],
        collection_logs=collection_logs,
        row_match_evidence=row_match_evidence,
    )
    review_target = next(item for item in review_rows if item["field"] == "报销比例")

    assert review_target["source_id"] == "S1"
    assert review_target["info_id"] == "I1"
    assert review_target["current_value"] == "80%"
    assert review_target["evidence_id"] == "T1,L1"
    assert review_target["attempt"] == "ocr_retry"
    assert review_target["review_status"] == "pending"
    assert review_target["reviewed_value"] == ""
    assert review_target["review_comment"] == ""
    assert "weak row match" in review_target["reason"]


def test_human_confirmed_review_status_adds_confidence_bonus():
    from field_confidence import calculate_field_confidence

    rows = [{"报销比例": "80%"}]
    evidence = [
        {
            "field": "报销比例",
            "value": "80%",
            "source": "table",
            "evidence": "表格显示报销比例80%",
            "table_index": 1,
            "col_index": 3,
            "review_status": "confirmed",
        }
    ]

    confidence_rows = calculate_field_confidence(rows, evidence, [], collection_logs=[])
    target = next(item for item in confidence_rows if item["field"] == "报销比例")

    assert target["review_status"] == "confirmed"
    assert target["confidence"] == 1.0
    assert "human confirmed" in target["reason"]
