from bs4 import BeautifulSoup


def _first_table(html):
    from table_normalizer import normalize_html_tables

    return normalize_html_tables(html)[0]


def test_normalizes_basic_table_to_markdown_and_coordinates():
    table = _first_table("<table><tr><th>类型</th><th>报销比例</th></tr><tr><td>门诊</td><td>80%</td></tr></table>")

    assert table.headers == ["类型", "报销比例"]
    assert table.rows[0][1].text == "80%"
    assert table.rows[0][1].row_index == 2
    assert table.rows[0][1].col_index == 2
    assert "| 类型 | 报销比例 |" in table.markdown


def test_rowspan_first_column_is_expanded():
    html = """
    <table>
      <tr><th>类型</th><th>医院类型</th><th>报销比例</th></tr>
      <tr><td rowspan="2">门诊</td><td>一级医院</td><td>80%</td></tr>
      <tr><td>二级医院</td><td>70%</td></tr>
    </table>
    """
    table = _first_table(html)

    assert table.rows[1][0].text == "门诊"
    assert table.rows[1][0].source_row == 2
    assert table.rows[1][0].source_col == 1


def test_colspan_and_multi_level_header_paths_are_preserved():
    html = """
    <table>
      <tr><th rowspan="2">类型</th><th colspan="2">门诊</th></tr>
      <tr><th>起付标准</th><th>报销比例</th></tr>
      <tr><td>普通门诊</td><td>100元</td><td>80%</td></tr>
    </table>
    """
    table = _first_table(html)

    assert table.header_paths[2] == ["门诊", "报销比例"]
    assert table.rows[0][2].header_path == ["门诊", "报销比例"]


def test_blank_cells_can_inherit_previous_row_value():
    table = _first_table("<table><tr><th>类型</th><th>报销比例</th></tr><tr><td>门诊</td><td>80%</td></tr><tr><td></td><td>70%</td></tr></table>")

    assert table.rows[1][0].text == "门诊"


def test_cell_text_handles_br_lists_footnotes_and_markdown_pipe_escape():
    html = """
    <table>
      <caption>待遇表</caption>
      <tr><th>类型</th><th>备注</th></tr>
      <tr><td>门诊<br>急诊</td><td><ul><li>A|B</li><li>脚注1</li></ul></td></tr>
    </table>
    """
    table = _first_table(html)

    assert table.caption == "待遇表"
    assert table.rows[0][0].text == "门诊 急诊"
    assert table.rows[0][1].text == "A|B 脚注1"
    assert "A\\|B" in table.markdown


def test_table_tag_input_is_supported():
    from table_normalizer import normalize_table

    soup = BeautifulSoup("<table><tr><th>类型</th></tr><tr><td>门诊</td></tr></table>", "html.parser")
    table = normalize_table(soup.table, table_index=3)

    assert table.table_index == 3
    assert table.rows[0][0].text == "门诊"
