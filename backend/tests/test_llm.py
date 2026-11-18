"""H1: the LLM module, with fake providers only. No test makes a real call."""
import pytest

from llm.client import BadRequest, LLMClient, LLMError, Transient, Unavailable, entries_from_env


def script(*outcomes):
    """A fake provider that returns or raises the given outcomes in turn, recording every call."""
    calls = []
    queue = list(outcomes)

    def call(system, user, model):
        calls.append(model)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    call.calls = calls
    return call


def client(fake, *models, retries=1):
    return LLMClient([("fake", m) for m in models], {"fake": fake}, retries=retries, sleep=lambda s: None)


def test_the_first_model_answers():
    fake = script('{"ok": true}')
    result = client(fake, "a", "b").complete("sys", "user")
    assert (result.text, result.answered_by, fake.calls) == ('{"ok": true}', "fake:a", ["a"])


def test_quota_moves_straight_to_the_next_model_and_reports_who_answered():
    fake = script(Unavailable("HTTP 429"), '{"ok": true}')
    result = client(fake, "a", "b").complete("sys", "user")
    assert (result.model, fake.calls) == ("b", ["a", "b"])
    assert [o for _, _, o in result.attempts] == ["unavailable: HTTP 429", "answered"]


def test_overload_is_retried_briefly_then_falls_through():
    fake = script(Transient("HTTP 503"), Transient("timed out"), '{"ok": true}')
    result = client(fake, "a", "b").complete("sys", "user")
    assert (result.model, fake.calls) == ("b", ["a", "a", "b"])


def test_a_retry_can_succeed_on_the_same_model():
    fake = script(Transient("HTTP 503"), '{"ok": true}')
    assert client(fake, "a", "b").complete("sys", "user").model == "a"


def test_a_bad_request_fails_clearly_without_trying_other_models():
    fake = script(BadRequest("HTTP 400: invalid argument"))
    with pytest.raises(LLMError, match="refused the request") as err:
        client(fake, "a", "b").complete("sys", "user")
    assert fake.calls == ["a"] and len(err.value.attempts) == 1


def test_every_model_failing_gives_one_plain_message_and_points_to_the_manual_path():
    fake = script(Unavailable("HTTP 429"), Transient("HTTP 503"), Transient("HTTP 503"))
    with pytest.raises(LLMError) as err:
        client(fake, "a", "b").complete("sys", "user")
    message = str(err.value)
    assert "unavailable right now" in message and "edit it directly" in message and "fake b: busy" in message
    assert [m for _, m, _ in err.value.attempts] == ["a", "b", "b"]


def test_an_empty_answer_counts_as_a_failure_of_that_model():
    fake = script("   ", '{"ok": true}')
    assert client(fake, "a", "b").complete("sys", "user").model == "b"


def test_no_models_configured_is_a_clear_error():
    with pytest.raises(LLMError, match="No AI model is configured"):
        LLMClient([], {}).complete("sys", "user")


@pytest.mark.parametrize("env, expected", [
    ({"LLM_MODELS": "gemini-3.6-flash, gemini-3.5-flash"}, [("gemini", "gemini-3.6-flash"), ("gemini", "gemini-3.5-flash")]),
    ({"LLM_MODELS": "groq:llama-x,gemini-3.6-flash", "LLM_PROVIDER": "gemini"}, [("groq", "llama-x"), ("gemini", "gemini-3.6-flash")]),
    ({"LLM_MODEL": "gemini-3.6-flash"}, [("gemini", "gemini-3.6-flash")]),
    ({"LLM_MODELS": "", "LLM_MODEL": "gemini-3.6-flash"}, [("gemini", "gemini-3.6-flash")]),
    ({"LLM_MODELS": " , ", "LLM_MODEL": "gemini-3.6-flash"}, [("gemini", "gemini-3.6-flash")]),
    ({"LLM_MODELS": "gemini:gemini-3.6-flash,gemini:gemini-3.5-flash", "LLM_MODEL": "ignored"},
     [("gemini", "gemini-3.6-flash"), ("gemini", "gemini-3.5-flash")]),
    ({}, []),
    ({}, []),
])
def test_model_list_from_the_environment(env, expected):
    assert entries_from_env(env) == expected


# ---------------------------------------------------------------- the Gemini provider's error mapping (no network)
import io as _io
import json as _json
import urllib.error as _urlerror

from llm import gemini


def _fake_urlopen(monkeypatch, *, error=None, reply=None):
    class Response(_io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        if error:
            raise error
        return Response(_json.dumps(reply).encode())
    monkeypatch.setenv("GEMINI", "test-key-not-real")
    monkeypatch.setattr(gemini.urllib.request, "urlopen", urlopen)


def test_a_429_keeps_googles_reason_and_moves_on(monkeypatch):
    body = _json.dumps({"error": {"code": 429, "message": "You exceeded your current quota.", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}, {"retryDelay": "41s"}]}})
    _fake_urlopen(monkeypatch, error=_urlerror.HTTPError("u", 429, "Too Many Requests", {}, _io.BytesIO(body.encode())))
    with pytest.raises(Unavailable) as exc:
        gemini.call_gemini("s", "u", "m")
    assert "PerDay" in str(exc.value) and "41s" in str(exc.value) and "exceeded" in str(exc.value)


def test_a_reply_cut_off_at_the_output_limit_is_never_a_draft(monkeypatch):
    _fake_urlopen(monkeypatch, reply={"candidates": [{"finishReason": "MAX_TOKENS",
                                                       "content": {"parts": [{"text": "{\"version\": \"5."}]}}]})
    with pytest.raises(Unavailable, match="cut off"):
        gemini.call_gemini("s", "u", "m")


def test_a_normal_reply_is_returned(monkeypatch):
    _fake_urlopen(monkeypatch, reply={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]})
    assert gemini.call_gemini("s", "u", "m") == "{}"
