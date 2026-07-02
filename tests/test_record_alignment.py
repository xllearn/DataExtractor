def test_align_records_matches_reversed_llm_rows_by_key_fields():
    from record_alignment import align_candidate_records

    base = [{"类型": "门诊", "报销比例": "80%"}, {"类型": "住院", "报销比例": "70%"}]
    candidates = [{"类型": "住院", "补助限额": "10万"}, {"类型": "门诊", "补助限额": "1万"}]

    aligned, evidence = align_candidate_records(base, candidates, "table", "llm")

    assert aligned[0]["补助限额"] == "1万"
    assert aligned[1]["补助限额"] == "10万"
    assert evidence[0]["similarity"] > 0
    assert "类型" in evidence[0]["matched_fields"]


def test_low_similarity_rows_are_not_forced():
    from record_alignment import align_candidate_records

    base = [{"类型": "门诊", "报销比例": "80%"}, {"类型": "住院", "报销比例": "70%"}]
    candidates = [{"类型": "药品", "报销比例": "20%"}]

    aligned, evidence = align_candidate_records(base, candidates, "table", "llm", threshold=0.5)

    assert aligned == [{}, {}]
    assert evidence[0]["reason"] == "below_threshold"


def test_extra_candidate_rows_are_returned_for_append():
    from record_alignment import align_sources

    base, aligned, evidence = align_sources(
        [{"类型": "门诊"}],
        [],
        [{"类型": "门诊"}, {"类型": "住院"}],
    )

    assert len(base) == 2
    assert aligned["llm"][1]["类型"] == "住院"
    assert any(item["reason"] == "extra_candidate_appended" for item in evidence)
