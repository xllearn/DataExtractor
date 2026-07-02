import ast
from pathlib import Path


def _pipeline_imports(tree):
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pipeline":
            imports.extend(alias for alias in node.names)
    return imports


def _pipeline_module_import_aliases(tree):
    aliases = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.extend(alias for alias in node.names if alias.name.split(".", 1)[0] == "pipeline")
    return aliases


def test_pipeline_module_import_aliases_detect_import_pipeline():
    tree = ast.parse("import pipeline\nimport pipeline as p\nimport pipeline.submodule\n")

    assert [alias.name for alias in _pipeline_module_import_aliases(tree)] == [
        "pipeline",
        "pipeline",
        "pipeline.submodule",
    ]


def test_main_imports_only_public_cli_pipeline_interfaces():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    allowed = {"create_empty_metadata", "extract_record_rows"}
    imported = [alias.name for alias in _pipeline_imports(tree)]
    module_imports = [alias.name for alias in _pipeline_module_import_aliases(tree)]

    assert module_imports == []
    assert [name for name in imported if name.startswith("_")] == []
    assert sorted(set(imported) - allowed) == []


def test_main_has_no_unused_pipeline_imports():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    imported_names = {
        alias.asname or alias.name
        for alias in _pipeline_imports(tree)
    }
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)

    assert sorted(imported_names - used_names) == []


def test_core_modules_compile_cleanly():
    for path in ["main.py", "pipeline.py", "table_normalizer.py", "record_alignment.py", "field_confidence.py", "prompt_registry.py"]:
        compile(Path(path).read_text(encoding="utf-8"), path, "exec")
