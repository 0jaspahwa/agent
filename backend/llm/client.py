"""H1: one small interface to the LLM (DECISIONS.md D32). The LLM only drafts; nothing it returns takes
effect without a person approving it, and nothing in the decision engine calls it.

LLMClient(entries, providers).complete(system, user) tries each (provider, model) entry in order:
  * overload or timeout (Transient): a short retry on the same model, then the next entry;
  * quota exhausted, or the model is not available to this key (Unavailable): the next entry at once;
  * a bad request or a rejected key (BadRequest): stop and fail clearly; another model would fail the same way.
It returns the text and which provider and model answered. If every entry fails, LLMError says so plainly.
"""
import os
import time
from dataclasses import dataclass, field


class Transient(Exception):
    """Overloaded (5xx) or timed out: worth one retry."""


class Unavailable(Exception):
    """Quota exhausted (429) or model not available to this key (404): try the next model."""


class BadRequest(Exception):
    """The request or the key is wrong (400, 401, 403): retrying another model will not help."""


class LLMError(Exception):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = attempts  # [(provider, model, outcome)]


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    attempts: tuple = field(default=())  # every (provider, model, outcome) tried, the answering one last

    @property
    def answered_by(self):
        return f"{self.provider}:{self.model}"


def entries_from_env(env=os.environ):
    """[(provider, model)] in the order to try them, from LLM_MODELS: comma-separated, each "provider:model" or
    just "model" (the provider is then LLM_PROVIDER, default gemini), so the list can cross providers. If
    LLM_MODELS is empty, the one model in LLM_MODEL."""
    default = env.get("LLM_PROVIDER", "gemini").strip() or "gemini"

    def split(value):
        return [n.strip() for n in (value or "").split(",") if n.strip()]
    names = split(env.get("LLM_MODELS")) or split(env.get("LLM_MODEL"))
    return [tuple(n.split(":", 1)) if ":" in n else (default, n) for n in names]


class LLMClient:
    def __init__(self, entries, providers, retries=1, wait=1.5, sleep=time.sleep):
        self.entries = list(entries)
        self.providers = providers  # name -> callable(system, user, model) -> text, raising the errors above
        self.retries, self.wait, self.sleep = retries, wait, sleep

    def complete(self, system, user):
        if not self.entries:
            raise LLMError("No AI model is configured (set LLM_MODELS or LLM_MODEL).", [])
        attempts = []
        for provider, model in self.entries:
            call = self.providers.get(provider)
            if call is None:
                attempts.append((provider, model, "unknown provider"))
                continue
            for attempt in range(self.retries + 1):
                try:
                    text = call(system, user, model)
                except Transient as exc:
                    attempts.append((provider, model, f"busy or timed out: {exc}"))
                    if attempt < self.retries:
                        self.sleep(self.wait * (attempt + 1))
                        continue
                    break
                except Unavailable as exc:
                    attempts.append((provider, model, f"unavailable: {exc}"))
                    break
                except BadRequest as exc:
                    attempts.append((provider, model, f"refused: {exc}"))
                    raise LLMError(f"The AI service refused the request ({provider} {model}): {exc}", attempts) from exc
                if not (text or "").strip():
                    attempts.append((provider, model, "empty answer"))
                    break
                attempts.append((provider, model, "answered"))
                return LLMResult(text, provider, model, tuple(attempts))
        tried = "; ".join(f"{p} {m}: {o}" for p, m, o in attempts)
        raise LLMError(f"The AI drafting service is unavailable right now ({tried}). You can start from the "
                       f"current policy and edit it directly instead.", attempts)
