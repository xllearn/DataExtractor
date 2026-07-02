import ast
from pathlib import Path


def test_main_does_not_import_private_pipeline_functions():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    private_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pipeline":
            private_imports.extend(alias.name for alias in node.names if alias.name.startswith("_"))
    assert private_imports == []


def test_core_modules_compile_cleanly():
    for path in ["main.py", "pipeline.py", "table_normalizer.py", "record_alignment.py", "field_confidence.py", "prompt_registry.py"]:
        compile(Path(path).read_text(encoding="utf-8"), path, "exec")
