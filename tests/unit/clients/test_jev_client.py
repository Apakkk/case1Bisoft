"""TypesafeJevClient with a scripted SDK stand-in: what goes to Jev and what comes back (no network, no tokens)."""

import pytest
from typesafe_sdk import TypeSafeError

from app.clients.jev_cache import JevAnswerCache
from app.clients.jev_client import OUTAGE_PAUSE_SECONDS, JevUnavailableError, RequestMeta, TypesafeJevClient
from tests.fakes import ScriptedSystemOne, jev_response

REEFER = {"type": "choice", "choice": "Reefer", "confidence": 0.97, "probabilities": {"Reefer": 0.97, "Dry": 0.03}}


def client(sdk: ScriptedSystemOne) -> TypesafeJevClient:
    return TypesafeJevClient("test-key", None, 5.0, client=sdk)


def test_the_token_count_and_the_answering_model_come_back_with_the_answer() -> None:
    sdk = ScriptedSystemOne(jev_response({"cargo_type": REEFER}))

    result = client(sdk).classify_order("frozen shrimp", ["Dry", "Reefer"], None)

    assert result.cargo_type is not None and result.cargo_type.choice == "Reefer"
    assert result.meta == RequestMeta(input_tokens=312, model="jev-1.14.0")
    assert len(sdk.requests) == 1


def test_a_missing_token_count_stays_unknown() -> None:
    sdk = ScriptedSystemOne(jev_response({"restricts": {"type": "noul", "noul": 0.04}}, tokens=None))

    result = client(sdk).note_has_restriction("Nationwide network.")

    assert result.meta == RequestMeta(input_tokens=None, model="jev-1.14.0")


def test_an_sdk_error_becomes_jev_unavailable() -> None:
    sdk = ScriptedSystemOne(error=TypeSafeError("timed out"))

    with pytest.raises(JevUnavailableError, match="timed out"):
        client(sdk).note_has_restriction("Nationwide network.")


# --- outage pause ------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


NOTE_ANSWER = {"restricts": {"type": "noul", "noul": 0.04}}


def test_after_a_failure_jev_is_not_asked_until_the_pause_ends() -> None:
    sdk, clock = ScriptedSystemOne(error=TypeSafeError("timed out")), Clock()
    jev = TypesafeJevClient("test-key", None, 5.0, client=sdk, clock=clock)

    with pytest.raises(JevUnavailableError, match="timed out"):
        jev.note_has_restriction("Nationwide network.")
    sdk.error, sdk.answer = None, jev_response(NOTE_ANSWER)  # Jev is back, but the pause is still on

    clock.now += OUTAGE_PAUSE_SECONDS - 1
    with pytest.raises(JevUnavailableError, match="recent failure"):
        jev.note_has_restriction("Nationwide network.")
    assert len(sdk.requests) == 1  # failed at once, without waiting for a timeout

    clock.now += 1
    assert jev.note_has_restriction("Nationwide network.").restriction_probability == 0.04
    assert len(sdk.requests) == 2


def test_answers_never_pause_anything() -> None:
    sdk = ScriptedSystemOne(jev_response(NOTE_ANSWER))
    jev = TypesafeJevClient("test-key", None, 5.0, client=sdk, clock=Clock())

    for _ in range(3):
        jev.note_has_restriction("Nationwide network.")

    assert len(sdk.requests) == 3


# --- answers from memory -----------------------------------------------------------------------


def cached_client(sdk: ScriptedSystemOne, clock: Clock | None = None) -> TypesafeJevClient:
    return TypesafeJevClient("test-key", None, 5.0, client=sdk, clock=clock or Clock(), cache=JevAnswerCache())


def test_the_same_question_is_sent_once() -> None:
    sdk = ScriptedSystemOne(jev_response(NOTE_ANSWER))
    jev = cached_client(sdk)

    first = jev.note_has_restriction("Hafta sonu çalışmıyoruz.")
    second = jev.note_has_restriction("Hafta sonu çalışmıyoruz.")

    assert len(sdk.requests) == 1
    assert first.meta == RequestMeta(312, "jev-1.14.0")
    assert second.meta == RequestMeta(0, "jev-1.14.0", cached=True)
    assert second.restriction_probability == first.restriction_probability


def test_another_text_is_another_question() -> None:
    sdk = ScriptedSystemOne(jev_response(NOTE_ANSWER))
    jev = cached_client(sdk)

    jev.note_has_restriction("Hafta sonu çalışmıyoruz.")
    jev.note_has_restriction("Hafta sonu çalışmıyoruz!")
    jev.note_has_restriction("hafta sonu çalışmıyoruz.")  # compared exactly: another question

    assert len(sdk.requests) == 3


def test_a_remembered_answer_is_used_while_jev_is_paused() -> None:
    sdk, clock = ScriptedSystemOne(jev_response(NOTE_ANSWER)), Clock()
    jev = cached_client(sdk, clock)
    jev.note_has_restriction("Nationwide network.")

    sdk.answer, sdk.error = None, TypeSafeError("timed out")
    with pytest.raises(JevUnavailableError):
        jev.note_has_restriction("Another note.")  # fails, and pauses Jev

    assert jev.note_has_restriction("Nationwide network.").meta.cached
    assert len(sdk.requests) == 2  # the remembered question needed no request
