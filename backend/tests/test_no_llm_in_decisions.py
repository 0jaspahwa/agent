"""The model describes, the code decides (APPROACH.md): no module on the decision path can reach the LLM.

The engine package, the batch run service and the loaders must not import the LLM client, the chat readers or the
amendment drafting code, directly or through each other. Checked on the source (AST), so it holds however the app
is wired at run time."""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DECISION_PATH = sorted((BACKEND / "engine").glob("*.py")) + sorted((BACKEND / "loaders").glob("*.py")) + [
    BACKEND / "services" / "runs.py", BACKEND / "services" / "snapshot.py", BACKEND / "db" / "ingest.py"]
FORBIDDEN = ("llm", "chat", "amendments", "services.chat", "services.amendments", "services.contracts")


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_no_decision_module_imports_the_llm_or_its_readers():
    found = {f"{p.relative_to(BACKEND)}: {name}" for p in DECISION_PATH for name in imports(p)
             if name.split(".")[0] in FORBIDDEN or name in FORBIDDEN}
    assert found == set()


def test_the_check_covers_the_whole_engine():
    assert len([p for p in DECISION_PATH if p.parent.name == "engine"]) >= 20
