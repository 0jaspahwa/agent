"""SQLAlchemy models: the tables of docs/data_model.md, nothing more.

Money, rates and quantities are Numeric (Python Decimal), never float. PR timestamps are naive (stored
exactly as given). JSON columns are JSONB on Postgres and JSON elsewhere (the tests also run on SQLite).
audit_log and buyer_actions are append-only: a trigger rejects UPDATE and DELETE (see session.py).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        Numeric, Text, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(16, 2)
Qty = Numeric(14, 3)
Rating = Numeric(5, 2)
Stamp = DateTime(timezone=False)  # PR created_at: as given, no zone, no conversion
AppTime = DateTime(timezone=True)  # written by the app


def checked(column, values):
    return CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=f"ck_{column}")


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- master data (engine input)
class Item(Base):
    __tablename__ = "items"
    item_code: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    item_type: Mapped[str] = mapped_column(Text)
    standard_price: Mapped[Decimal] = mapped_column(Money)


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (checked("status", ["Active", "Blocked", "Inactive"]),)
    supplier_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    categories: Mapped[list] = mapped_column(Json)
    status: Mapped[str] = mapped_column(Text)
    on_time_pct: Mapped[Decimal] = mapped_column(Rating)
    quality_rating: Mapped[Decimal] = mapped_column(Rating)


class Plant(Base):
    __tablename__ = "plants"
    plant: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class PoHistory(Base):
    __tablename__ = "po_history"
    __table_args__ = (Index("ix_po_history_item_date", "item_code", "po_date"),)
    po_number: Mapped[str] = mapped_column(Text, primary_key=True)
    po_date: Mapped[date] = mapped_column(Date)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"))
    item_code: Mapped[str] = mapped_column(ForeignKey("items.item_code"))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    uom: Mapped[str] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    plant: Mapped[str] = mapped_column(ForeignKey("plants.plant"))
    delivered_on_time: Mapped[bool] = mapped_column(Boolean)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (checked("source", ["register", "pdf", "manual"]),)
    contract_id: Mapped[str] = mapped_column(Text, primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"))
    supplier_name: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    value_cap: Mapped[Decimal] = mapped_column(Money)
    consumed_value: Mapped[Decimal] = mapped_column(Money)  # as at consumed_as_of; 0 for pdf/manual
    consumed_as_of: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())


class ContractLine(Base):
    __tablename__ = "contract_lines"
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id"), primary_key=True)
    item_code: Mapped[str] = mapped_column(ForeignKey("items.item_code"), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str] = mapped_column(Text)
    rate: Mapped[Decimal] = mapped_column(Money)


# ---------------------------------------------------------------- policy
class PolicyVersion(Base):
    """Approved and withdrawn versions are immutable: a trigger (session.py) refuses any change except
    approved -> withdrawn, and refuses deleting them."""
    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version"),
                      checked("status", ["draft", "approved", "discarded", "withdrawn"]),
                      checked("drafting_status", ["drafting", "ready", "failed"]))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date)  # None only for an incomplete draft
    status: Mapped[str] = mapped_column(Text)
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"))
    draft_info: Mapped[dict | None] = mapped_column(Json)  # not_expressed, translation_notes, LLM attempts
    # Making the draft (an LLM draft is made in the background): drafting -> ready | failed (with a reason).
    drafting_status: Mapped[str] = mapped_column(Text, default="ready")
    drafting_started_at: Mapped[datetime | None] = mapped_column(AppTime)
    drafting_finished_at: Mapped[datetime | None] = mapped_column(AppTime)
    drafting_error: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[str | None] = mapped_column(Text)  # who discarded or withdrew it
    closed_at: Mapped[datetime | None] = mapped_column(AppTime)
    close_comment: Mapped[str | None] = mapped_column(Text)
    document: Mapped[dict | None] = mapped_column(Json)  # None only while drafting, or if drafting failed
    source_document_name: Mapped[str | None] = mapped_column(Text)
    source_document_text: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(Text)
    drafted_by: Mapped[str] = mapped_column(Text)
    impact_summary: Mapped[dict | None] = mapped_column(Json)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(AppTime)


# ---------------------------------------------------------------- intake
class PrBatch(Base):
    __tablename__ = "pr_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    csv_text: Mapped[str] = mapped_column(Text)
    csv_sha256: Mapped[str] = mapped_column(Text)
    line_count: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())


class PrLine(Base):
    __tablename__ = "pr_lines"
    __table_args__ = (
        checked("source", ["batch", "chat"]),  # batch duplicates are stored and reported (line check V3)
        Index("ux_pr_lines_chat", "pr_no", "pr_line", unique=True,
              postgresql_where=text("source = 'chat'"), sqlite_where=text("source = 'chat'")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("pr_batches.id"))
    pr_no: Mapped[str] = mapped_column(Text)
    pr_line: Mapped[str] = mapped_column(Text)  # as given
    created_at: Mapped[datetime | None] = mapped_column(Stamp)  # None when unreadable
    requester: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    plant: Mapped[str] = mapped_column(Text)  # not an FK: an unknown plant must be stored and reported
    item_code: Mapped[str | None] = mapped_column(Text)  # not an FK: an unknown code is reported
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    uom: Mapped[str | None] = mapped_column(Text)
    estimated_unit_price: Mapped[Decimal | None] = mapped_column(Money)
    need_by_date: Mapped[date | None] = mapped_column(Date)
    urgency: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(Json)
    created_by: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())


# ---------------------------------------------------------------- runs and outputs
class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (checked("kind", ["batch", "chat"]), checked("status", ["running", "done", "failed"]))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("pr_batches.id"))
    policy_version_ids: Mapped[list] = mapped_column(Json)
    inputs: Mapped[dict] = mapped_column(Json)  # lines, master data, policy documents, contract_baseline
    inputs_sha256: Mapped[str] = mapped_column(Text)
    export_sha256: Mapped[str | None] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(AppTime)


class Requirement(Base):
    """The engine's decision is never changed. A buyer's approval or override is a BuyerAction beside it; `status`
    and `row_version` make those actions safe when two buyers click at once (conditional update, B4)."""
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("run_id", "group_id"), checked("status", ["open", "approved", "overridden"]))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    group_id: Mapped[str] = mapped_column(Text)
    item_code: Mapped[str] = mapped_column(Text)
    plant: Mapped[str] = mapped_column(Text)
    requirement_date: Mapped[date] = mapped_column(Date)
    first_created_at: Mapped[datetime] = mapped_column(Stamp)
    total_quantity: Mapped[Decimal] = mapped_column(Qty)
    value_inr: Mapped[Decimal | None] = mapped_column(Money)
    valuation_source: Mapped[str | None] = mapped_column(Text)
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id"))
    rule_id: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(Text)
    supplier_id: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    suggested_supplier_ids: Mapped[list] = mapped_column(Json)
    contract_id: Mapped[str | None] = mapped_column(Text)
    relied_on: Mapped[dict] = mapped_column(Json)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    row_version: Mapped[int] = mapped_column(Integer, default=1)


EXPORT_COLUMNS = ["pr_no", "pr_line", "resolved_item_code", "group_id", "po_id", "decision", "route",
                  "supplier_id", "unit_price", "group_value_inr", "suggested_supplier_ids", "policy_version",
                  "reason"]


class Decision(Base):
    """One export row per PR line per run; the 13 export columns hold the exact text written to the CSV."""
    __tablename__ = "decisions"
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    pr_line_id: Mapped[int] = mapped_column(ForeignKey("pr_lines.id"), primary_key=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"))
    row_order: Mapped[int] = mapped_column(Integer)
    pr_no: Mapped[str] = mapped_column(Text)
    pr_line: Mapped[str] = mapped_column(Text)
    resolved_item_code: Mapped[str] = mapped_column(Text)
    group_id: Mapped[str] = mapped_column(Text)
    po_id: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(Text)
    supplier_id: Mapped[str] = mapped_column(Text)
    unit_price: Mapped[str] = mapped_column(Text)
    group_value_inr: Mapped[str] = mapped_column(Text)
    suggested_supplier_ids: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- workspace outcomes
class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("run_id", "po_number"), checked("status", ["proposed", "approved", "cancelled"]))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    po_number: Mapped[str] = mapped_column(Text)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"))
    plant: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(Text)
    first_requirement_at: Mapped[datetime] = mapped_column(Stamp)
    total_value: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(Text, default="proposed")


class PoLine(Base):
    __tablename__ = "po_lines"
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), unique=True)
    item_code: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    value: Mapped[Decimal] = mapped_column(Money)


class SourcingRequest(Base):
    __tablename__ = "sourcing_requests"
    __table_args__ = (checked("status", ["proposed", "issued", "cancelled"]),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), unique=True)
    route: Mapped[str] = mapped_column(Text)
    suggested_supplier_ids: Mapped[list] = mapped_column(Json)
    suggest_count_requested: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="proposed")


class BuyerAction(Base):
    """Append-only: approvals and overrides sit beside the original decision, which is never changed."""
    __tablename__ = "buyer_actions"
    __table_args__ = (
        checked("action", ["approve", "override"]),
        CheckConstraint("action <> 'override' OR (comment IS NOT NULL AND length(trim(comment)) > 0)",
                        name="ck_override_needs_comment"),
    )
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"))
    action: Mapped[str] = mapped_column(Text)
    new_route: Mapped[str | None] = mapped_column(Text)
    new_supplier_id: Mapped[str | None] = mapped_column(Text)
    new_unit_price: Mapped[Decimal | None] = mapped_column(Money)
    new_suggested_supplier_ids: Mapped[list | None] = mapped_column(Json)
    comment: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())


# ---------------------------------------------------------------- chat intake (B2)
class ChatConversation(Base):
    """One requester's conversation. `state` is the draft PR the code builds up (chat/conversation.py)."""
    __tablename__ = "chat_conversations"
    __table_args__ = (checked("status", ["open", "created", "cancelled", "policy_draft"]),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    state: Mapped[dict] = mapped_column(Json)
    pr_no: Mapped[str | None] = mapped_column(Text)  # the PR it created
    policy_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"))  # a policy draft it started
    created_at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(AppTime)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (checked("sender", ["user", "assistant"]),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversations.id"))
    sender: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(Json, default=dict)  # choices, card, how the message was read
    at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())


# ---------------------------------------------------------------- audit
class AuditLog(Base):
    """Append-only (trigger): every user action and every LLM call or failure."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    at: Mapped[datetime] = mapped_column(AppTime, server_default=func.now())
    actor: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(Json, default=dict)


APPEND_ONLY_TABLES = ("audit_log", "buyer_actions")
