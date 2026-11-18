"""Database connection and table creation (no migrations tool: tables are created on startup)."""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from db.models import APPEND_ONLY_TABLES, Base

DEFAULT_URL = "postgresql+psycopg://corvo:corvo@localhost:5432/corvo"


def database_url(url=None):
    """The configured URL, with the psycopg driver named: hosts such as Render give postgres://... or
    postgresql://..., which SQLAlchemy would otherwise try to open with a driver we do not install."""
    url = url or os.getenv("DATABASE_URL") or DEFAULT_URL
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url=None):
    return create_engine(database_url(url), pool_pre_ping=True)


def _append_only_ddl(dialect, table):
    if dialect == "postgresql":
        return [
            """CREATE OR REPLACE FUNCTION reject_change() RETURNS trigger AS $$
               BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql""",
            f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}",
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION reject_change()",
            f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}",
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION reject_change()",
        ]
    if dialect == "sqlite":
        return [f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op.upper()} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END" for op in ("update", "delete")]
    raise NotImplementedError(f"append-only triggers for {dialect}")


FROZEN = ("document", "version", "effective_from", "approved_by", "approved_at", "impact_summary",
          "change_summary", "source_document_text", "policy_id")
IMMUTABLE = "approved policy versions are immutable (only withdrawal is allowed)"


def _policy_version_ddl(dialect):
    """Approved and withdrawn versions: no field may change except approved -> withdrawn, and no deletes."""
    if dialect == "postgresql":
        changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in FROZEN)
        return [
            f"""CREATE OR REPLACE FUNCTION protect_policy_version() RETURNS trigger AS $$
               BEGIN
                 IF OLD.status IN ('approved', 'withdrawn') THEN
                   IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'approved policy versions cannot be deleted'; END IF;
                   IF {changed} OR NOT (NEW.status = OLD.status OR (OLD.status = 'approved' AND NEW.status = 'withdrawn'))
                   THEN RAISE EXCEPTION '{IMMUTABLE}'; END IF;
                 END IF;
                 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                 RETURN NEW;
               END; $$ LANGUAGE plpgsql""",
            "DROP TRIGGER IF EXISTS policy_versions_protect ON policy_versions",
            "CREATE TRIGGER policy_versions_protect BEFORE UPDATE OR DELETE ON policy_versions "
            "FOR EACH ROW EXECUTE FUNCTION protect_policy_version()",
        ]
    if dialect == "sqlite":
        changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in FROZEN)
        return [
            f"CREATE TRIGGER IF NOT EXISTS policy_versions_protect BEFORE UPDATE ON policy_versions "
            f"WHEN OLD.status IN ('approved', 'withdrawn') AND ({changed} OR NOT (NEW.status = OLD.status OR "
            f"(OLD.status = 'approved' AND NEW.status = 'withdrawn'))) BEGIN SELECT RAISE(ABORT, '{IMMUTABLE}'); END",
            "CREATE TRIGGER IF NOT EXISTS policy_versions_no_delete BEFORE DELETE ON policy_versions "
            "WHEN OLD.status IN ('approved', 'withdrawn') BEGIN SELECT RAISE(ABORT, 'approved policy versions cannot be deleted'); END",
        ]
    raise NotImplementedError(f"policy version triggers for {dialect}")


def init_db(engine):
    """Create missing tables and (re)install the protective triggers. Safe to run on every startup.
    (create_all adds missing tables, not missing columns: a database made by an older version must be reset.)"""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in APPEND_ONLY_TABLES:
            for statement in _append_only_ddl(engine.dialect.name, table):
                conn.execute(text(statement))
        for statement in _policy_version_ddl(engine.dialect.name):
            conn.execute(text(statement))


def reset_db(engine):
    """Drop every table of the app (RESET_DB_ON_START, docs/deploy.md). Everything stored is lost: runs, drafts,
    approvals, chat requests, audit log. The caller reseeds."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:  # CASCADE also removes tables an older version of the app created
            names = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
            for name in names:
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
    else:
        Base.metadata.drop_all(engine)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
