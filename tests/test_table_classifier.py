from table_classifier import classify_table


def test_classifies_treatment_table_with_ratio_amount_and_context():
    result = classify_table(
        headers=["保障责任", "人员类型", "报销比例"],
        rows=[["住院医疗费用", "参保人", "80%"]],
    )

    assert result.table_type in {"treatment_table", "coverage_table"}
    assert result.confidence >= 0.75
    assert result.confidence_level == "high"
    assert "amount_or_ratio" in result.positive_signals


def test_high_confidence_noise_overrides_single_amount_or_ratio_cell():
    result = classify_table(
        headers=["共保体", "保险公司", "服务电话", "赔付比例"],
        rows=[["主承保", "示例保险公司", "95500", "80%"]],
    )

    assert result.table_type == "co_insurer_table"
    assert result.confidence >= 0.75
    assert result.confidence_level == "high"
    assert "保险公司" in result.negative_signals


def test_unknown_table_remains_candidate_when_signals_are_mixed():
    result = classify_table(headers=["项目", "说明"], rows=[["待遇说明", "以页面公示为准"]])

    assert result.table_type == "unknown_table"
    assert result.confidence < 0.75
