"""The Gemini provider: one REST call (generateContent, JSON output mode), errors mapped to the client's kinds.
The key is the GEMINI environment variable (.env locally, the host's settings when deployed)."""
import json
import os
import socket
import urllib.error
import urllib.request

from llm.client import BadRequest, Transient, Unavailable

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def reason(detail):
    """Google's own explanation from an error body, kept short: the message, which quota, when to retry."""
    try:
        error = json.loads(detail).get("error", {})
    except ValueError:
        return detail[:200]
    parts = [str(error.get("message", ""))[:200]]
    for d in error.get("details") or []:
        for v in d.get("violations") or []:
            if v.get("quotaId"):
                parts.append(f"quota {v['quotaId']}")
        if d.get("retryDelay"):
            parts.append(f"retry after {d['retryDelay']}")
    return "; ".join(p for p in parts if p)


def call_gemini(system, user, model, timeout=240):
    key = os.getenv("GEMINI") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise BadRequest("no Gemini key is set (GEMINI)")
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    request = urllib.request.Request(URL.format(model=model), data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = reason(exc.read().decode(errors="replace")[:2000])
        if exc.code in (429, 404):
            raise Unavailable(f"HTTP {exc.code} ({detail})") from exc
        if exc.code >= 500:
            raise Transient(f"HTTP {exc.code}") from exc
        raise BadRequest(f"HTTP {exc.code}: {detail}") from exc
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise Transient(str(exc)) from exc
    candidate = (reply.get("candidates") or [{}])[0]
    if candidate.get("finishReason") == "MAX_TOKENS":  # a cut-off reply is never passed on as a draft
        raise Unavailable("the reply was cut off at the model's output limit")
    parts = (candidate.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


PROVIDERS = {"gemini": call_gemini}
CHAT_TIMEOUT = 20  # seconds: a chat reply must not wait for a slow model; the pattern reader takes over


def chat_providers(timeout=CHAT_TIMEOUT):
    """The same providers with a short timeout, for reading chat messages (or a contract's text)."""
    return {name: (lambda system, user, model, _fn=fn: _fn(system, user, model, timeout=timeout))
            for name, fn in PROVIDERS.items()}
