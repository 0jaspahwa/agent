"""Run the whole app locally with one command, without Docker or Postgres: a SQLite file in scripts/out/, the
React interface built on first run, and http://localhost:8000.

By default no LLM is used at all (amendment drafts fail plainly and are entered by hand; chat uses the pattern
reader), so nothing is ever sent to a model. With --llm, the LLM settings in .env are used (LLM_MODELS, GEMINI).

    python scripts/dev_server.py            # http://localhost:8000
    python scripts/dev_server.py --llm      # with the AI settings from .env
    python scripts/dev_server.py --fresh    # start from a new database (the old one is deleted)
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def build_interface():
    """Build frontend/dist if it is missing (installing the packages first if needed)."""
    if (FRONTEND / "dist" / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        print("Node.js (npm) is not installed: the API and the plain pages at /ops work, the interface at / does not.")
        return
    if not (FRONTEND / "node_modules").is_dir():
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm", action="store_true", help="use the LLM settings from .env")
    parser.add_argument("--fresh", action="store_true", help="delete the local database first")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    out = ROOT / "scripts" / "out"
    out.mkdir(parents=True, exist_ok=True)
    db = out / "dev.db"
    if args.fresh and db.exists():
        db.unlink()
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{db}")
    if args.llm:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    else:
        os.environ["LLM_MODELS"], os.environ["LLM_MODEL"], os.environ["CHAT_LLM"] = "", "", "off"
    build_interface()
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn
    print(f"Open http://localhost:{args.port}  (plain pages: /ops, API docs: /docs)")
    uvicorn.run("main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
