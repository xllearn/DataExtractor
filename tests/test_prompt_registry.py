def test_prompt_registry_builds_stable_hashes_and_versions():
    from prompt_registry import build_prompt

    first = build_prompt(
        "v3",
        record={"Title": "A"},
        clean_text="正文",
        tables_text="表格",
        image_ocr_text="",
        today="20260702",
    )
    second = build_prompt(
        "v3",
        record={"Title": "A"},
        clean_text="正文",
        tables_text="表格",
        image_ocr_text="",
        today="20260702",
    )

    assert first.version == "v3"
    assert first.prompt_hash == second.prompt_hash
    assert "不要编造字段" in first.text
    assert "必须返回 JSON object" in first.text


def test_prompt_registry_supports_v2_fallback():
    from prompt_registry import build_prompt

    prompt = build_prompt("v2", record={}, clean_text="", tables_text="", image_ocr_text="", today="20260702")

    assert prompt.version == "v2"
    assert prompt.prompt_hash
