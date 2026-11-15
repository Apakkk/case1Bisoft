"""Minimal, token-frugal connectivity check for the Jev (TypeSafe) API.

Run: make smoke-jev   (needs TYPESAFE_API_KEY in .env)

1. Lists the models available to the account (metadata only, no tokens) so a
   version can be pinned in JEV_MODEL.
2. Sends ONE tiny classification (a few input tokens) and prints the answer
   shape, confidence, per-label probabilities, usage and latency.
"""

import os
import time

from typesafe_sdk import Choice, TypeSafeClient


def main() -> None:
    model = os.environ.get("JEV_MODEL") or None
    with TypeSafeClient() as client:
        print("# Available models")
        for m in client.models.list().models:
            print(f"  {m.name:<24} {m.release_date}  {m.description[:70]}")

        started = time.perf_counter()
        result = client.system_one(
            state="frozen shrimp",
            questions={"cargo": Choice(criteria={"Dry": None, "Reefer": None, "Hazardous": None})},
            model=model,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        answer = result.choices["cargo"]
        probs = ", ".join(f"{k}={v:.3f}" for k, v in answer.probabilities.items())
        print(f"\n# One call: model={result.model}, {elapsed_ms:.0f} ms, input_tokens={result.usage.input_tokens}")
        print(f"  cargo -> {answer.choice} (confidence {answer.confidence:.3f}; {probs})")


if __name__ == "__main__":
    main()
