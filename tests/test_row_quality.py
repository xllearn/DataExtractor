from row_quality import evaluate_row_quality
from utils import EXCEL_HEADERS


def test_metadata_only_row_does_not_enter_main_result():
    row = {
        EXCEL_HEADERS[3]: "上海市",
        EXCEL_HEADERS[9]: "沪惠保",
    }

    quality = evaluate_row_quality(row)

    assert quality.metadata_nonblank_count >= 2
    assert quality.content_core_nonblank_count == 0
    assert quality.treatment_nonblank_count == 0
    assert quality.target_sheet == "low_value"
    assert quality.should_enter_main_result is False


def test_isolated_amount_or_ratio_without_context_does_not_enter_main_result():
    row = {
        EXCEL_HEADERS[18]: "80%",
        "_table_index": 1,
        "_table_type": "unknown_table",
        "_table_confidence": 0.6,
    }

    quality = evaluate_row_quality(row)

    assert quality.has_amount_or_ratio is True
    assert quality.has_treatment_context is False
    assert quality.target_sheet == "candidate"
    assert quality.should_enter_main_result is False


def test_ratio_with_person_type_enters_main_result():
    row = {
        EXCEL_HEADERS[10]: "参保人",
        EXCEL_HEADERS[18]: "80%",
        "_table_index": 1,
        "_table_type": "treatment_table",
        "_table_confidence": 0.86,
    }

    quality = evaluate_row_quality(row)

    assert quality.has_treatment_context is True
    assert quality.has_treatment_context_source == "field"
    assert quality.target_sheet == "main"
    assert quality.should_enter_main_result is True


def test_deductible_with_hospital_type_enters_main_result():
    row = {
        EXCEL_HEADERS[13]: "二级及以上医院",
        EXCEL_HEADERS[16]: "1.5万元",
        "_table_index": 1,
        "_table_type": "coverage_table",
        "_table_confidence": 0.8,
    }

    quality = evaluate_row_quality(row)

    assert quality.target_sheet == "main"
    assert quality.should_enter_main_result is True


def test_header_or_caption_context_can_admit_treatment_row():
    row = {
        EXCEL_HEADERS[18]: "70%",
        "_table_index": 1,
        "_headers": "住院 医疗费用 报销比例",
        "_caption": "保障责任",
        "_table_type": "treatment_table",
        "_table_confidence": 0.82,
    }

    quality = evaluate_row_quality(row)

    assert quality.has_treatment_context is True
    assert "header" in quality.has_treatment_context_source
    assert quality.target_sheet == "main"


def test_noise_table_is_low_value_even_with_amount_or_ratio():
    row = {
        EXCEL_HEADERS[18]: "80%",
        "_table_index": 1,
        "_table_type": "co_insurer_table",
        "_table_confidence": 0.9,
        "_headers": "保险公司 服务电话 赔付比例",
    }

    quality = evaluate_row_quality(row)

    assert quality.target_sheet == "low_value"
    assert quality.should_enter_main_result is False
