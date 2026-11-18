"""The engine never reads the current date or time: every date comes from its inputs (PR lines, PO history,
contracts, policy versions). Checked on the source of every module in backend/engine."""
import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "engine"
CLOCK_CALLS = {"now", "today", "utcnow", "time", "time_ns", "localtime", "gmtime", "monotonic", "perf_counter",
               "process_time", "ctime"}
CLOCK_MODULES = {"time", "calendar"}


def offences(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name in CLOCK_CALLS:
                found.append(f"{path.name}:{node.lineno} calls {name}()")
        if isinstance(node, ast.Import):
            found += [f"{path.name}:{node.lineno} imports {a.name}" for a in node.names if a.name in CLOCK_MODULES]
        if isinstance(node, ast.ImportFrom) and node.module in CLOCK_MODULES:
            found.append(f"{path.name}:{node.lineno} imports from {node.module}")
    return found


def test_no_engine_module_reads_the_clock():
    modules = sorted(ENGINE.glob("*.py"))
    assert len(modules) > 15
    assert [o for m in modules for o in offences(m)] == []


def test_the_check_would_catch_a_clock_read(tmp_path):
    sample = tmp_path / "bad.py"
    sample.write_text("import time\nfrom datetime import date\nx = date.today()\ny = time.time()\n")
    assert offences(sample) == ["bad.py:1 imports time", "bad.py:3 calls today()", "bad.py:4 calls time()"]
