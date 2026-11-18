"""B2: chat intake, stored. A conversation is a row with the state the code builds up (chat/conversation.py)
and its messages. Each turn: read the message (LLM extraction, or the pattern reader), let the state machine
decide what to ask, store both messages. Creating stores the PR lines (source chat) and runs the engine over
every open chat line (D15), then says in one sentence per line what will happen next.

Text a user types is data, never instructions: the state machine has no "approve" or "change the rules" step,
and a policy change asked for in chat only starts an amendment draft for review (Procurement only).
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from chat import conversation as cv
from chat.extract import read_message
from chat.reader import Reading, plant_aliases
from db.models import AuditLog, BuyerAction, ChatConversation, ChatMessage, Decision, PrLine
from loaders import database
from services import amendments, runs
from services.snapshot import plain

IST = timezone(timedelta(hours=5, minutes=30))  # PR creation times are plant-local (naive), as in the batch files
ROUTE_WORDS = {
    "CONTRACT_PO": "will be placed as a contract PO with {supplier} at {price}",
    "EMERGENCY_PO": "will be placed as an emergency PO with {supplier} at {price}",
    "SPOT_PO": "will be placed as a spot PO with {supplier} at {price}",
    "RFQ": "goes to an RFQ with {n} suggested suppliers",
    "RFP": "goes to an RFP with {n} suggested suppliers",
    "CAPEX_SOURCING": "is Capex, so it needs capex approval and goes to sourcing with {n} suggested suppliers",
    "NEW_ITEM_SOURCING": "is a new item, so it goes to sourcing",
}
AI_DOWN = "The AI reader is unavailable, so I am reading your messages with simple rules."


class ChatError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(IST)


def _context(session, role, today):
    master = database.load_master(session)
    policy = master.policies[-1].document if master.policies else {}
    settings = policy["parameters"]["matching"]
    return cv.Context(master.items, settings, master.plants, plant_aliases(master.plants), today, role), master


def _say(session, conv, sender, text, **payload):
    session.add(ChatMessage(conversation_id=conv.id, sender=sender, text=text, payload=plain(payload)))


def start(session, user, role):
    conv = ChatConversation(user_name=user, role=role, status="open", state=cv.new_state(), updated_at=now())
    session.add(conv)
    session.flush()
    _say(session, conv, "assistant", f"Hello {user}. What do you need? For example: 200 nitrile gloves for Chakan "
                                     f"by next Friday.", choices=[], card=None)
    session.commit()
    return conv


def _get(session, conv_id, user):
    conv = session.get(ChatConversation, conv_id)
    if conv is None:
        raise ChatError("There is no such conversation.", 404)
    if conv.user_name != user:
        raise ChatError("This conversation belongs to someone else.", 403)
    return conv


def view(session, conv_id, user):
    conv = _get(session, conv_id, user)
    msgs = session.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.id)).all()
    last = next((m for m in reversed(msgs) if m.sender == "assistant"), None)
    ctx, _ = _context(session, conv.role, now().date())
    state = conv.state
    return {"id": conv.id, "status": conv.status, "pr_no": conv.pr_no, "policy_version_id": conv.policy_version_id,
            "messages": [{"sender": m.sender, "text": m.text, "at": plain(m.at), **(m.payload or {})} for m in msgs],
            "pending": state["pending"], "draft": cv.card(state, ctx), "missing": cv.missing(state),
            "choices": (last.payload or {}).get("choices", []) if last and conv.status == "open" else [],
            "card": (last.payload or {}).get("card") if last and conv.status == "open" else None}


def post(session, conv_id, user, role, event, llm_client=None, draft_client=None):
    """One turn. Returns (view, ids of policy drafts for the caller to make in the background)."""
    conv = _get(session, conv_id, user)
    if conv.status != "open":
        raise ChatError("This conversation is finished. Start a new request.", 409)
    today = now().date()
    ctx, master = _context(session, role, today)
    state = conv.state
    how, reading = None, None
    if event.get("type") == "message":
        text = str(event.get("text") or "").strip()[:2000]
        if not text:
            raise ChatError("Type a message first.")
        _say(session, conv, "user", text)
        reading, how = read_message(text, today, ctx.aliases, state["pending"], llm_client)
    else:
        label = event.get("label") or event.get("type")
        _say(session, conv, "user", str(label), event=plain(event))
        reading = Reading()
    state, reply = cv.handle(state, event, reading, ctx)
    prefix = ""
    if how and how.startswith("reader (AI unavailable") and not state.get("told_ai_down"):
        state["told_ai_down"] = True
        prefix = AI_DOWN + " "
    jobs = []
    if reply["do"] == "cancel":
        conv.status = "cancelled"
        _say(session, conv, "assistant", reply["text"], choices=[], card=None, read_by=how)
    elif reply["do"] == "policy":
        text = event.get("text", "")
        row = amendments.start_draft(session, user, draft_client, text, "chat")
        conv.status, conv.policy_version_id = "policy_draft", row.id
        jobs.append(row.id)
        _say(session, conv, "assistant", prefix + reply["text"] + f" Review it under Policy, version {row.version}.",
             choices=[], card=None, read_by=how, link=f"/policies/{row.id}")
    elif reply["do"] == "create":
        pr_no, sentences = create_pr(session, conv, state, user, master)
        conv.status, conv.pr_no = "created", pr_no
        _say(session, conv, "assistant", f"Created {pr_no}. " + " ".join(sentences), choices=[], card=None, read_by=how)
    else:
        _say(session, conv, "assistant", prefix + reply["text"], choices=reply["choices"], card=reply["card"], read_by=how)
    conv.state, conv.updated_at = state, now()
    session.add(AuditLog(actor=user, actor_role=role or "", action="chat.message", entity_type="chat_conversation",
                         entity_id=str(conv.id), details=plain({"event": event.get("type"), "read_by": how,
                                                                "do": reply["do"]})))
    session.commit()
    return view(session, conv.id, user), jobs


def next_pr_no(session, year):
    prefix = f"PRC-{year % 100:02d}-"
    taken = session.scalars(select(PrLine.pr_no).where(PrLine.source == "chat", PrLine.pr_no.like(prefix + "%"))).all()
    n = max((int(p[len(prefix):]) for p in taken if p[len(prefix):].isdigit()), default=0) + 1
    return f"{prefix}{n:05d}"


def create_pr(session, conv, state, user, master):
    """Store the PR lines (source chat), run the engine over open chat lines, and say what happens next."""
    created = now()
    pr_no = next_pr_no(session, created.year)
    for i, ln in enumerate(state["lines"], start=1):
        session.add(PrLine(source="chat", batch_id=None, pr_no=pr_no, pr_line=str(i),
                           created_at=created.replace(tzinfo=None, microsecond=0), requester=user, department=None,
                           plant=state["plant"], item_code=ln["item_code"],
                           description=ln["description"] or ln["text"], quantity=Decimal(ln["quantity"]),
                           uom=ln["unit"], estimated_unit_price=Decimal(ln["price"]) if ln["price"] else None,
                           need_by_date=date.fromisoformat(state["need_by"]), urgency=state["urgency"],
                           raw={"conversation_id": conv.id, "typed": ln["text"]}, created_by=user))
    session.add(AuditLog(actor=user, actor_role=conv.role, action="chat.create_pr", entity_type="pr", entity_id=pr_no,
                         details={"conversation_id": conv.id, "lines": len(state["lines"])}))
    session.flush()
    run, result = runs.process_chat(session, user)
    return pr_no, next_steps(result, pr_no, master)


def next_steps(result, pr_no, master):
    rows = [r.values for r in result.rows]
    mine = [r for r in rows if r["pr_no"] == pr_no]
    out = []
    for r in mine:
        subject = "This" if len(mine) == 1 else f"Line {r['pr_line']}"
        if r["route"] == "NOT_PROCESSED":
            out.append(f"{subject} cannot be processed: {r['reason']}")
            continue
        others = [f"{o['pr_no']}/{o['pr_line']}" for o in rows if o["group_id"] == r["group_id"] and o["pr_no"] != pr_no]
        joins = f"joins requirement {r['group_id']} (with {', '.join(others)}) and" if others else \
            f"is requirement {r['group_id']} and"
        supplier = master.suppliers.get(r["supplier_id"])
        n = len([s for s in r["suggested_supplier_ids"].split(";") if s])
        words = ROUTE_WORDS[r["route"]].format(supplier=supplier.name if supplier else r["supplier_id"],
                                               price=f"₹{r['unit_price']} each", n=n)
        out.append(f"{subject} {joins} {words}.")
    out.append("A buyer reviews it before anything is ordered.")
    return out


def my_requests(session, user):
    """The caller's chat PRs, newest first, each line with its latest decision and any buyer action."""
    lines = session.scalars(select(PrLine).where(PrLine.source == "chat", PrLine.created_by == user)
                            .order_by(PrLine.id.desc())).all()
    out = {}
    for ln in lines:
        decision = session.scalars(select(Decision).where(Decision.pr_line_id == ln.id)
                                   .order_by(Decision.run_id.desc())).first()
        action = None
        if decision and decision.requirement_id:
            action = session.scalars(select(BuyerAction).where(BuyerAction.requirement_id == decision.requirement_id)
                                     .order_by(BuyerAction.id.desc())).first()
        status = ("Approved" if action.action == "approve" else "Overridden") + f" by {action.actor}" if action else \
            ("Not processed" if decision and decision.route == "NOT_PROCESSED" else "Waiting for a buyer")
        pr = out.setdefault(ln.pr_no, {"pr_no": ln.pr_no, "created_at": plain(ln.created_at), "plant": ln.plant,
                                       "need_by": plain(ln.need_by_date), "urgency": ln.urgency, "lines": []})
        pr["lines"].append({"line": ln.pr_line, "item_code": ln.item_code or "NEW", "description": ln.description,
                            "quantity": plain(ln.quantity), "unit": ln.uom, "status": status,
                            "route": decision.route if decision else None,
                            "group_id": decision.group_id if decision else None,
                            "reason": decision.reason if decision else None})
    for pr in out.values():
        pr["lines"].sort(key=lambda x: int(x["line"]))
    return list(out.values())
