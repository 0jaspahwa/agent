"""H6: the amendment workflow on a seeded database, with a fake LLM only."""
import copy
import json

import pytest
from sqlalchemy import select, text

from db.models import AuditLog, PolicyVersion
from db.seed import seed
from db.session import make_session_factory
from engine.policy import load_policy
from kitdata import DATA_DIR
from llm.client import LLMClient, LLMError, Unavailable
from services import amendments as svc
from services.runs import process_batch

from kit_required import skip_module_without_kit

skip_module_without_kit()  # reads the task kit (data/)

BASE = load_policy("5.0")
SAMPLE = (DATA_DIR / "pr_batches" / "sample_pr_batch.csv").read_text(encoding="utf-8")
GOLDEN = (DATA_DIR.parent / "backend" / "tests" / "golden" / "sample_pr_batch_decisions.csv")


@pytest.fixture
def session(db_engine):
    seed(db_engine)
    with make_session_factory(db_engine)() as s:
        yield s


def fake_client(*replies):
    queue = list(replies)

    def call(system, user, model):
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return LLMClient([("fake", "model-a"), ("fake", "model-b")], {"fake": call}, sleep=lambda s: None)


def proposal(effective_from="2026-04-01", spot=150000, **extra):
    doc = copy.deepcopy(BASE)
    doc.update(version="5.1", supersedes="5.0", effective_from=effective_from, source_document="A-1",
               change_summary="Spot PO limit lowered")
    doc["parameters"]["limits"]["spot_po"]["value"] = spot
    doc.update(extra)
    return doc


def reply(doc, not_expressed=()):
    return as_operations(doc, not_expressed, ["fake note"])


def as_operations(doc, not_expressed=(), notes=()):
    """An operations-mode reply (the default DRAFT_MODE) that turns the base policy into `doc`."""
    ops = [{"op": "set", "path": f"parameters.{k}", "value": v} for k, v in doc["parameters"].items()]
    ops += [{"op": "replace", "section": "rules", "id": r["id"], "item": r} for r in doc["rules"]]
    return json.dumps({"version": doc["version"], "effective_from": doc["effective_from"],
                       "change_summary": doc["change_summary"], "source_document": doc["source_document"],
                       "operations": ops, "not_expressed": list(not_expressed), "translation_notes": list(notes)})


def actions(session):
    return [a.action for a in session.scalars(select(AuditLog).where(AuditLog.entity_type == "policy_version")
                                              .order_by(AuditLog.id))]


def spot_count(export):
    return sum(",SPOT_PO," in line for line in export.splitlines())


def golden_text():
    return GOLDEN.read_text(encoding="utf-8")


def test_a_good_draft_is_explained_previewed_and_approved(session):
    process_batch(session, "sample.csv", SAMPLE, "tester")
    row = svc.create_draft(session, "asha", fake_client(reply(proposal(), ["one clause the schema cannot hold"])),
                           "Spot limit below 1,50,000 from 1 Apr 2026.", "A-1.md")
    view = svc.view(session, row.id)
    assert view["status"] == "draft" and view["errors"] == [] and view["drafted_by"] == "llm:fake:model-a"
    assert view["not_expressed"] == ["one clause the schema cannot hold"]
    assert any("1,50,000" in sentence for sentence in view["diff"])
    preview = svc.preview(session, row.id)
    assert preview["changed"] > 0 and preview["routes_after"]["SPOT_PO"] < preview["routes_before"]["SPOT_PO"]
    approved = svc.approve(session, row.id, "Asha Rao", "Procurement")
    assert (approved.status, approved.approved_by) == ("approved", "Asha Rao") and approved.approved_at
    assert approved.impact_summary["changed"] == preview["changed"]
    assert approved.source_document_text.startswith("Spot limit")
    _, _, export, _ = process_batch(session, "sample.csv", SAMPLE, "tester")
    assert spot_count(export) == preview["routes_after"]["SPOT_PO"]
    assert ",5.1," in export
    assert actions(session) == ["policy.draft_started", "policy.draft", "policy.approve"]


def test_an_invalid_draft_shows_readable_errors_and_cannot_be_approved(session):
    bad = proposal()
    bad["rules"][1]["when"] = {"<": [{"var": "requirement.valeu_inr"}, 5]}
    row = svc.create_draft(session, "asha", fake_client(reply(bad)), "text", "A.md")
    errors = svc.view(session, row.id)["errors"]
    assert any("requirement.valeu_inr" in e for e in errors)
    with pytest.raises(svc.AmendmentError) as exc:
        svc.approve(session, row.id, "Asha", "Procurement")
    assert exc.value.status == 422 and "requirement.valeu_inr" in str(exc.value)
    with pytest.raises(svc.AmendmentError):
        svc.preview(session, row.id)


def test_an_edited_draft_is_revalidated_and_rediffed(session):
    bad = proposal()
    bad["rules"][1]["when"] = {"<": [{"var": "requirement.valeu_inr"}, 5]}
    row = svc.create_draft(session, "asha", fake_client(reply(bad)), "text")
    svc.update_draft(session, row.id, proposal(spot=175000), "asha")
    view = svc.view(session, row.id)
    assert view["errors"] == [] and any("1,75,000" in s for s in view["diff"])
    assert actions(session) == ["policy.draft_started", "policy.draft", "policy.edit"]


def test_a_draft_without_the_llm_is_incomplete_until_it_has_an_effective_date(session):
    row = svc.create_draft(session, "asha", from_current=True)
    view = svc.view(session, row.id)
    assert view["incomplete"] and view["drafted_by"] == "manual:asha" and view["version"] == "5.1"
    assert view["errors"][0].startswith("effective_from")
    with pytest.raises(svc.AmendmentError):
        svc.approve(session, row.id, "Asha", "Procurement")
    doc = view["document"]
    doc["effective_from"] = "2026-04-01"
    svc.update_draft(session, row.id, doc, "asha")
    assert svc.view(session, row.id)["errors"] == []
    assert svc.approve(session, row.id, "Asha", "Procurement").status == "approved"


@pytest.mark.parametrize("user,role", [("", "Procurement"), ("  ", "Procurement"), ("Asha", "Buyer"), ("Asha", None)])
def test_approval_needs_a_name_and_the_procurement_role(session, user, role):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")
    with pytest.raises(svc.AmendmentError) as exc:
        svc.approve(session, row.id, user, role)
    assert exc.value.status == 403
    assert session.get(PolicyVersion, row.id).status == "draft"


def test_an_approved_version_cannot_be_changed_or_deleted(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")
    svc.approve(session, row.id, "Asha", "Procurement")
    with pytest.raises(svc.AmendmentError):
        svc.update_draft(session, row.id, proposal(spot=1), "asha")
    with pytest.raises(svc.AmendmentError):
        svc.discard(session, row.id, "asha")
    for statement in (f"UPDATE policy_versions SET effective_from = '2020-01-01' WHERE id = {row.id}",
                      f"UPDATE policy_versions SET status = 'draft' WHERE id = {row.id}",
                      f"DELETE FROM policy_versions WHERE id = {row.id}"):
        with pytest.raises(Exception, match="immutable|cannot be deleted"):
            session.execute(text(statement))
        session.rollback()


def test_a_draft_can_be_discarded(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")
    svc.discard(session, row.id, "asha", "not needed")
    assert (session.get(PolicyVersion, row.id).status, svc.view(session, row.id)["close_comment"]) == ("discarded", "not needed")
    with pytest.raises(svc.AmendmentError):
        svc.approve(session, row.id, "Asha", "Procurement")


def test_withdrawing_restores_the_previous_behaviour(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")
    svc.approve(session, row.id, "Asha", "Procurement")
    _, _, changed, _ = process_batch(session, "sample.csv", SAMPLE, "tester")
    assert changed != golden_text()
    with pytest.raises(svc.AmendmentError):
        svc.withdraw(session, row.id, "Asha", "Procurement", "  ")  # a comment is required
    svc.withdraw(session, row.id, "Asha", "Procurement", "approved by mistake")
    _, _, export, _ = process_batch(session, "sample.csv", SAMPLE, "tester")
    assert export == golden_text()
    assert actions(session) == ["policy.draft_started", "policy.draft", "policy.approve", "policy.withdraw"]


def test_the_only_approved_version_cannot_be_withdrawn(session):
    only = session.scalar(select(PolicyVersion).where(PolicyVersion.version == "5.0"))
    with pytest.raises(svc.AmendmentError) as exc:
        svc.withdraw(session, only.id, "Asha", "Procurement", "why not")
    assert exc.value.status == 409


def test_a_mid_batch_effective_date_applies_only_to_later_requirements(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal("2026-11-10", spot=1))), "text")
    svc.approve(session, row.id, "Asha", "Procurement")
    _, result, _, _ = process_batch(session, "sample.csv", SAMPLE, "tester")
    versions = {r.values["policy_version"] for r in result.rows if r.values["route"] != "NOT_PROCESSED"}
    assert versions == {"5.0", "5.1"}
    by_line = {f"{r.values['pr_no']}/{r.values['pr_line']}": r.values for r in result.rows}
    assert by_line["PR-26-00146/1"]["policy_version"] == "5.0"  # requirement 11-02


def test_a_label_already_used_is_refused_on_edit(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")
    with pytest.raises(svc.AmendmentError) as exc:
        svc.update_draft(session, row.id, proposal(version="5.0"), "asha")
    assert exc.value.status == 409


def test_an_llm_failure_is_plain_logged_and_the_manual_path_still_works(session):
    down = fake_client(Unavailable("429 quota"), Unavailable("429 quota"))
    failed = svc.create_draft(session, "asha", down, "Spot limit ...", "A.md")
    assert (failed.status, failed.drafting_status, failed.document) == ("draft", "failed", None)
    assert "unavailable right now" in failed.drafting_error and "edit it" in failed.drafting_error
    failure = session.scalar(select(AuditLog).where(AuditLog.action == "llm.failure"))
    assert failure.details["attempts"] and failure.comment == failed.drafting_error
    for action in (lambda: svc.preview(session, failed.id), lambda: svc.approve(session, failed.id, "Asha", "Procurement"),
                   lambda: svc.update_draft(session, failed.id, proposal(), "asha")):
        with pytest.raises(svc.AmendmentError, match="Drafting failed"):
            action()
    svc.discard(session, failed.id, "asha", "AI down")
    row = svc.create_draft(session, "asha", from_current=True)
    assert (row.status, row.drafting_status) == ("draft", "ready")


# ---------------------------------------------------------------- H7: process under one named version
def test_a_named_version_reproduces_run_1_after_an_amendment_is_approved(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")
    svc.approve(session, row.id, "Asha", "Procurement")
    run, _, export, _ = process_batch(session, "sample.csv", SAMPLE, "tester", version="5.0")
    assert export == golden_text()
    assert run.inputs["policy_mode"]["mode"] == "named_version" and run.inputs["policy_mode"]["version"] == "5.0"
    by_date, _, changed, _ = process_batch(session, "sample.csv", SAMPLE, "tester")
    assert changed != golden_text() and by_date.inputs["policy_mode"]["mode"] == "by_requirement_date"


def test_a_named_version_applies_to_requirements_dated_before_its_effective_date(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal("2026-12-01", spot=150000))), "text")
    svc.approve(session, row.id, "Asha", "Procurement")
    _, _, by_date, _ = process_batch(session, "sample.csv", SAMPLE, "tester")
    assert by_date == golden_text()  # effective after the whole batch: nothing changes by date
    _, result, pinned, _ = process_batch(session, "sample.csv", SAMPLE, "tester", version="5.1")
    assert spot_count(pinned) < spot_count(by_date)
    assert {r.values["policy_version"] for r in result.rows} == {"5.1"}


def test_an_unknown_or_unapproved_version_is_refused_before_anything_is_stored(session):
    from db.models import PrBatch
    from services.runs import UnknownVersion
    svc.create_draft(session, "asha", fake_client(reply(proposal())), "text")  # 5.1 exists only as a draft
    for label in ("9.9", "5.1"):
        with pytest.raises(UnknownVersion, match="approved: 5.0"):
            process_batch(session, "sample.csv", SAMPLE, "tester", version=label)
    assert session.scalars(select(PrBatch)).all() == []



# ---------------------------------------------------------------- background drafting
from datetime import datetime, timedelta, timezone  # noqa: E402


def test_a_draft_starts_as_drafting_and_the_background_part_makes_it_ready(session):
    llm = fake_client(reply(proposal()))
    row = svc.start_draft(session, "asha", llm, "Spot limit ...", "A.md")
    assert (row.drafting_status, row.document, row.version) == ("drafting", None, "5.1")
    assert svc.view(session, row.id)["drafting_status"] == "drafting"
    with pytest.raises(svc.AmendmentError, match="still drafting"):
        svc.approve(session, row.id, "Asha", "Procurement")
    svc.run_draft(svc.make_factory(session), row.id, llm, clock=iter([100.0, 112.5]).__next__)
    session.expire_all()
    view = svc.view(session, row.id)
    assert (view["drafting_status"], view["drafting_seconds"], view["drafted_by"]) == ("ready", 12.5, "llm:fake:model-a")
    assert view["draft_mode"] == "operations" and view["operations"] and view["errors"] == []


def test_a_draft_stuck_for_more_than_five_minutes_is_marked_failed(session):
    row = svc.start_draft(session, "asha", fake_client(), "text")
    assert svc.expire_stuck(session, now=datetime.now(timezone.utc) + timedelta(minutes=4)) == 0
    assert svc.expire_stuck(session, now=datetime.now(timezone.utc) + timedelta(minutes=6)) == 1
    session.expire_all()
    view = svc.view(session, row.id)
    assert view["drafting_status"] == "failed" and "within 5 minutes" in view["drafting_error"]


def test_a_late_answer_never_overwrites_a_failed_or_discarded_draft(session):
    llm = fake_client(reply(proposal()), reply(proposal()))
    late = svc.start_draft(session, "asha", llm, "text")
    svc.expire_stuck(session, now=datetime.now(timezone.utc) + timedelta(minutes=6))
    svc.run_draft(svc.make_factory(session), late.id, llm)
    gone = svc.start_draft(session, "asha", llm, "text")
    svc.discard(session, gone.id, "asha", "changed my mind")
    svc.run_draft(svc.make_factory(session), gone.id, llm)
    session.expire_all()
    assert session.get(PolicyVersion, late.id).drafting_status == "failed"
    assert session.get(PolicyVersion, gone.id).status == "discarded"
    assert session.get(PolicyVersion, gone.id).document is None


def test_a_restart_marks_drafts_in_progress_as_failed(session):
    row = svc.start_draft(session, "asha", fake_client(), "text")
    assert svc.fail_interrupted(session) == 1
    session.expire_all()
    assert "server restarted" in session.get(PolicyVersion, row.id).drafting_error


def test_an_unexpected_error_in_the_background_leaves_a_clear_failure(session):
    class Broken:
        def complete(self, system, user):
            raise RuntimeError("boom")
    row = svc.start_draft(session, "asha", Broken(), "text")
    svc.run_draft(svc.make_factory(session), row.id, Broken())
    session.expire_all()
    assert "unexpected error (RuntimeError)" in session.get(PolicyVersion, row.id).drafting_error


def test_the_label_the_model_proposes_is_kept_if_free(session):
    row = svc.create_draft(session, "asha", fake_client(reply(proposal(version="5.7"))), "text")
    assert row.version == "5.7" and row.draft_info["proposed_version"] == "5.7"
