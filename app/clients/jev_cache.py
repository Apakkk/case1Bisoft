"""Answers Jev already gave, kept in this process's memory: the same question about the same text is paid for once.

The key is everything sent to Jev: the configured model, the state (order fields, order note, the eligible carriers'
descriptions) and the questions themselves (their instructions and labels, carrier names included). Changing any of
these makes a new question, so an answer is never reused for something Jev was not asked. Prices, rules and distances
are not part of an answer, so a quote is still worked out afresh from today's data on every request.

The model is pinned by default (JEV_MODEL, jev-1.14.0), but the API was not shown to refuse a name it does not know,
and JEV_MODEL may be set to the `jev-latest` alias. So an answer is used only while it is younger than MAX_AGE_SECONDS
and comes from the model that answered most recently: when the answering version changes, the first fresh answer
reports it and older answers stop being used. The memory is emptied by a restart.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from typesafe_sdk import SystemOneResponse

MAX_ENTRIES = 1_000  # a few MB at most; the least recently used answer goes first
MAX_AGE_SECONDS = 24 * 3600.0


def question_key(model: str | None, state: Any, questions: Mapping[str, Any]) -> str:
    """A digest of exactly what one request sends to Jev."""
    asked = {name: [type(q).__name__, q.model_dump(mode="json")] for name, q in questions.items()}
    raw = json.dumps([model, state, asked], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class _Entry:
    answer: SystemOneResponse
    stored_at: float


class JevAnswerCache:
    """Thread-safe: the API answers several requests at once."""

    def __init__(
        self,
        *,
        max_entries: int = MAX_ENTRIES,
        max_age_seconds: float = MAX_AGE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._max_entries = max_entries
        self._max_age = max_age_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._latest_model: str | None = None  # the model of the most recent fresh answer

    def get(self, key: str) -> SystemOneResponse | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            too_old = self._clock() - entry.stored_at >= self._max_age
            other_model = self._latest_model is not None and entry.answer.model != self._latest_model
            if too_old or other_model:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return entry.answer

    def put(self, key: str, answer: SystemOneResponse) -> None:
        with self._lock:
            self._latest_model = answer.model
            self._entries[key] = _Entry(answer, self._clock())
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
