"""OpenAI-backed candidate evaluator.

One chat completion, the ELI-41 prompt as the user message. The prompt itself
carries the rules and the schema, so the same text a recruiter would paste
into Claude is what the model here answers — the in-app and the manual path
cannot drift apart. Low temperature: this is an evaluation, not prose.
"""

from __future__ import annotations

_SYSTEM = (
    "Du bist ein sorgfältiger Recruiting-Analyst. Du hältst dich exakt an das "
    "vorgegebene Ausgabeschema, belegst jede Aussage mit dem Material und "
    "erfindest nichts."
)


class OpenAIEvaluator:
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI  # imported here so the SDK stays optional

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def evaluate(self, prompt: str) -> str:
        completion = self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        return (completion.choices[0].message.content or "").strip()
