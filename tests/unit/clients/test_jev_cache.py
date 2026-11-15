"""JevAnswerCache: what makes two questions the same, and when a remembered answer stops being used."""

from typing import Any

from typesafe_sdk import Choice, Noul

from app.clients.jev_cache import JevAnswerCache, question_key
from tests.fakes import jev_response

NOTE = {"restricts": Noul(instructions="Does this description restrict orders?")}
ORDER_STATE: dict[str, Any] = {
    "order": {"origin": "Miami", "destination": "Orlando", "container_size_ft": 40, "cargo_type": "Dry"},
    "carrier_descriptions": {"M-Logistics": "Nationwide.", "S-Logistics": "Florida only."},
}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def answer(model: str = "jev-1.14.0") -> Any:
    return jev_response({"restricts": {"type": "noul", "noul": 0.1}}, model=model)


def test_the_key_covers_everything_sent_to_jev() -> None:
    base = question_key(None, ORDER_STATE, NOTE)
    other_description = {
        **ORDER_STATE,
        "carrier_descriptions": {**ORDER_STATE["carrier_descriptions"], "S-Logistics": "x"},
    }
    other_order = {**ORDER_STATE, "order": {**ORDER_STATE["order"], "container_size_ft": 45}}
    reworded = {"restricts": Noul(instructions="Does this description limit orders?")}
    other_kind = {"restricts": Choice(instructions="Does this description restrict orders?", criteria={"yes": None})}

    assert question_key(None, ORDER_STATE, NOTE) == base  # the same request
    assert question_key(None, other_description, NOTE) != base
    assert question_key(None, other_order, NOTE) != base
    assert question_key(None, ORDER_STATE, reworded) != base  # a prompt change needs no manual version
    assert question_key(None, ORDER_STATE, other_kind) != base
    assert question_key("jev-preview", ORDER_STATE, NOTE) != base


def test_an_answer_is_kept_for_a_day() -> None:
    clock = Clock()
    cache = JevAnswerCache(clock=clock)
    cache.put("k", answer())

    clock.now += 24 * 3600 - 1
    assert cache.get("k") is not None
    clock.now += 1
    assert cache.get("k") is None


def test_answers_of_an_earlier_model_stop_being_used_once_a_new_one_answers() -> None:
    cache = JevAnswerCache(clock=Clock())
    cache.put("old", answer("jev-1.14.0"))

    cache.put("new", answer("jev-1.15.0"))  # the jev-latest alias moved

    assert cache.get("old") is None
    assert cache.get("new") is not None


def test_the_least_recently_used_answer_goes_first() -> None:
    cache = JevAnswerCache(max_entries=2, clock=Clock())
    cache.put("a", answer())
    cache.put("b", answer())
    cache.get("a")  # used again: "b" is now the oldest

    cache.put("c", answer())

    assert (cache.get("a") is not None, cache.get("b") is None, cache.get("c") is not None) == (True, True, True)
    assert len(cache) == 2
