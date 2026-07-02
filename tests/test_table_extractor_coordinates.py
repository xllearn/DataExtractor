def test_extract_table_records_uses_normalized_coordinates_and_header_path():
    from html_parser import parse_html_content
    from table_extractor import extract_table_records

    html = """
    <table>
      <tr><th rowspan="2">类型</th><th colspan="2">门诊</th></tr>
      <tr><th>起付标准</th><th>报销比例</th></tr>
      <tr><td>普通门诊</td><td>100元</td><td>80%</td></tr>
    </table>
    """
    parsed = parse_html_content(html)
    result = extract_table_records(html, parsed.tables_text, normalized_tables=parsed.normalized_tables)
    ratio_evidence = next(item for item in result.field_evidence if item["field"] == "报销比例")

    assert result.records[0]["报销比例"] == "80%"
    assert ratio_evidence["table_index"] == 1
    assert ratio_evidence["row_index"] == 3
    assert ratio_evidence["col_index"] == 3
    assert ratio_evidence["header"] == "报销比例"
    assert ratio_evidence["header_path"] == "门诊 > 报销比例"
    assert ratio_evidence["cell_text"] == "80%"
    assert ratio_evidence["evidence_id"] == "table:1:3:3"
