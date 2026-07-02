import yaml

from utils import EXCEL_HEADERS


STANDARDIZED_TYPE = EXCEL_HEADERS[8]
VISIT_REGION = EXCEL_HEADERS[12]
REIMBURSEMENT_RATIO = EXCEL_HEADERS[18]
SUBSIDY_LIMIT = EXCEL_HEADERS[17]


def test_match_fields_are_known_excel_or_allowed_internal_fields():
    from record_alignment import MATCH_FIELDS

    allowed = set(EXCEL_HEADERS) | {"info_id"}

    assert set(MATCH_FIELDS) <= allowed
    assert STANDARDIZED_TYPE in MATCH_FIELDS
    assert VISIT_REGION in MATCH_FIELDS
    assert "标准化类型" not in MATCH_FIELDS
    assert "就诊场景" not in MATCH_FIELDS


def test_align_records_matches_reversed_rows_by_standardized_type_and_visit_region():
    from record_alignment import align_candidate_records

    base = [
        {STANDARDIZED_TYPE: "门诊慢特病", VISIT_REGION: "省内", REIMBURSEMENT_RATIO: "80%"},
        {STANDARDIZED_TYPE: "住院", VISIT_REGION: "省外", REIMBURSEMENT_RATIO: "70%"},
    ]
    candidates = [
        {STANDARDIZED_TYPE: "住院", VISIT_REGION: "省外", SUBSIDY_LIMIT: "10万"},
        {STANDARDIZED_TYPE: "门诊慢特病", VISIT_REGION: "省内", SUBSIDY_LIMIT: "1万"},
    ]

    aligned, evidence = align_candidate_records(base, candidates, "table", "llm")

    assert aligned[0][SUBSIDY_LIMIT] == "1万"
    assert aligned[1][SUBSIDY_LIMIT] == "10万"
    assert STANDARDIZED_TYPE in evidence[0]["matched_fields"]
    assert VISIT_REGION in evidence[0]["matched_fields"]


def test_alignment_evidence_marks_strong_matches_without_review():
    from record_alignment import align_candidate_records

    aligned, evidence = align_candidate_records(
        [{REIMBURSEMENT_RATIO: "80%"}],
        [{REIMBURSEMENT_RATIO: "80%", SUBSIDY_LIMIT: "1万"}],
        "table",
        "llm",
        min_similarity=0.55,
        strong_similarity=0.82,
    )

    assert aligned[0][SUBSIDY_LIMIT] == "1万"
    assert evidence[0]["match_level"] == "strong"
    assert evidence[0]["needs_review"] is False


def test_alignment_evidence_marks_weak_matches_for_review_but_aligns():
    from record_alignment import align_candidate_records

    aligned, evidence = align_candidate_records(
        [{REIMBURSEMENT_RATIO: "80%"}],
        [{REIMBURSEMENT_RATIO: "70%", SUBSIDY_LIMIT: "1万"}],
        "table",
        "llm",
        min_similarity=0.55,
        strong_similarity=0.82,
    )

    assert aligned[0][SUBSIDY_LIMIT] == "1万"
    assert 0.55 <= evidence[0]["similarity"] < 0.82
    assert evidence[0]["match_level"] == "weak"
    assert evidence[0]["needs_review"] is True


def test_alignment_evidence_marks_below_threshold_without_alignment():
    from record_alignment import align_candidate_records

    aligned, evidence = align_candidate_records(
        [{STANDARDIZED_TYPE: "门诊"}],
        [{STANDARDIZED_TYPE: "住院", SUBSIDY_LIMIT: "1万"}],
        "table",
        "llm",
        min_similarity=0.55,
        strong_similarity=0.82,
    )

    assert aligned == [{}]
    assert evidence[0]["match_level"] == "below_threshold"
    assert evidence[0]["needs_review"] is True


def test_single_row_default_keeps_alignment_but_marks_review_from_similarity():
    from record_alignment import align_sources

    base, aligned, evidence = align_sources(
        [{STANDARDIZED_TYPE: "门诊"}],
        [],
        [{STANDARDIZED_TYPE: "住院", SUBSIDY_LIMIT: "1万"}],
        min_similarity=0.55,
        strong_similarity=0.82,
    )

    llm_evidence = next(item for item in evidence if item["source_b"] == "llm")
    assert len(base) == 1
    assert aligned["llm"][0][SUBSIDY_LIMIT] == "1万"
    assert llm_evidence["reason"] == "single_row_default"
    assert llm_evidence["match_level"] == "below_threshold"
    assert llm_evidence["needs_review"] is True


def test_alignment_defaults_are_loaded_from_quality_thresholds_config():
    from record_alignment import load_alignment_thresholds

    payload = yaml.safe_load(open("config/quality_thresholds.yml", encoding="utf-8")) or {}
    thresholds = load_alignment_thresholds()

    assert payload["alignment"]["min_similarity"] == 0.55
    assert payload["alignment"]["strong_similarity"] == 0.82
    assert thresholds.min_similarity == 0.55
    assert thresholds.strong_similarity == 0.82
    assert thresholds.min_similarity >= 0.5


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
