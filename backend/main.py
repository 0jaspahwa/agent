"""FastAPI app. On startup it creates the tables and seeds policy v5.0 and, if DATA_DIR (default data/) holds the
task kit, the kit (both safe to repeat); then serves the API, the plain operations pages at /ops and the React
interface at / (frontend/dist). The kit is not in the repo: without it the app starts with empty master data, says
so on every screen and in /api/health, and Procurement uploads it under Load kit data.

Run from the repo root:  uvicorn main:app --app-dir backend --reload   (needs DATABASE_URL, or Postgres on
localhost:5432 with user/password/db corvo). Set SEED_ON_STARTUP=false to skip seeding.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import func, select

from api import admin, amendments_page, batches, chat, contracts, insights, ops, policies, runs, spa, workspace
from db.models import Contract, Item, PoHistory, PolicyVersion, Supplier
from db.seed import seed
from kitdata import DATA_DIR, NO_KIT_NOTICE, kit_present
from db.session import init_db, make_engine, make_session_factory, reset_db
from llm.client import LLMClient, entries_from_env
from llm.gemini import PROVIDERS, chat_providers
from services import amendments

log = logging.getLogger("uvicorn.error")  # shown in the host's log with the server's own messages

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = make_engine()
    if os.getenv("RESET_DB_ON_START", "false").strip().lower() == "true":
        # For one deploy after a schema change only (docs/deploy.md): every table is dropped and rebuilt.
        reset_db(app.state.engine)
        log.warning("RESET_DB_ON_START=true: dropped every table, recreated them and reseeded. Set it back to "
                    "false now. If the kit was uploaded rather than in DATA_DIR, load it again under Load kit data.")
        seed(app.state.engine)
    elif os.getenv("SEED_ON_STARTUP", "true").lower() == "true":
        seed(app.state.engine)
    else:
        init_db(app.state.engine)
    if not kit_present(DATA_DIR):
        with app.state.engine.connect() as conn:
            items = conn.execute(select(func.count()).select_from(Item)).scalar_one()
        if items:
            log.info("No kit files in DATA_DIR (%s); using the kit loaded earlier (%d items).", DATA_DIR, items)
        else:
            log.warning("%s No kit files in DATA_DIR (%s), and none uploaded yet: master data is empty until a "
                        "Procurement user loads the kit (POST /api/admin/load-kit).", NO_KIT_NOTICE, DATA_DIR)
    app.state.session_factory = make_session_factory(app.state.engine)
    ops.STATE["engine"] = app.state.engine  # the plain pages' no-kit banner
    with app.state.session_factory() as session:  # no background draft survives a restart
        amendments.fail_interrupted(session)
    # Drafting only (never decisions). Nothing is called until someone asks for a draft.
    app.state.llm_client = LLMClient(entries_from_env(), PROVIDERS)
    # Chat reads a message with the LLM (short timeout, no retry); CHAT_LLM=off uses the pattern reader only.
    chat_on = os.getenv("CHAT_LLM", "on").lower() != "off" and entries_from_env()
    app.state.chat_llm_client = LLMClient(entries_from_env(), chat_providers(), retries=0) if chat_on else None
    # Reading a contract PDF the deterministic reader cannot read (asked for by the buyer; a draft to check).
    app.state.contract_llm_client = LLMClient(entries_from_env(), chat_providers(60), retries=0) if entries_from_env() else None
    yield
    app.state.engine.dispose()


app = FastAPI(title="Corvo procurement decisions", lifespan=lifespan)
app.include_router(batches.router)
app.include_router(admin.router)
app.include_router(runs.router)
app.include_router(policies.router)
app.include_router(chat.router)
app.include_router(workspace.router)
app.include_router(contracts.router)
app.include_router(insights.router)
app.include_router(ops.router)
app.include_router(amendments_page.router)


@app.get("/api/health")
def health() -> dict:
    with app.state.engine.connect() as conn:
        counts = {m.__tablename__: conn.execute(select(func.count()).select_from(m)).scalar_one()
                  for m in (Item, Supplier, PoHistory, Contract, PolicyVersion)}
    loaded = counts["items"] > 0 and counts["suppliers"] > 0
    body = {"status": "ok", "database": app.state.engine.dialect.name, "kit_loaded": loaded, "rows": counts}
    if not loaded:
        body["notice"] = NO_KIT_NOTICE
    return body


spa.mount(app)  # last: the React interface takes every path no other route claims
