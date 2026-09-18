"""
LLM Interpreter using Google Gemini REST API.

For teammates:
    from app.services.llm_service import interpret_notes
    entries = interpret_notes(notes, battery)

`entries` is the spec-exact directive_interpretation list.
"""

from __future__ import annotations

import json
import logging
import os

import requests
from dotenv import load_dotenv

from app.services.guardrails import (
    GuardrailError,
    build_entry,
    no_op_entry,
    validate_final,
)

load_dotenv()

log = logging.getLogger("llm_service")

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "25"))

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/{model}:generateContent"
)


SYSTEM_PROMPT = """You interpret campus energy operator notes for a 24-hour
battery/solar/grid schedule (hours 0-23 of TODAY).

For each note choose EXACTLY ONE directive_type:

solar_reduction:
- Solar generation is reduced.
- Give factor = fraction of solar remaining (0..1).

minimum_battery_reserve:
- Battery must keep minimum stored energy.
- Use minimum_energy_kwh or reserve_percent_of_capacity.

no_charge_window:
- Battery charging is not allowed.

no_discharge_window:
- Battery discharge is not allowed.

max_grid_window:
- Grid import must not exceed a limit.
- Give max_grid_kwh.

no_op:
- The note does not affect today's energy schedule.

Rules:
- Ignore unrelated topics.
- Ignore future/past events.
- Do not invent new directive types.
- Copy numbers exactly.
- Return hours as start_hour and end_hour.
- Use end_hour as exclusive.

Return ONLY JSON.

Format:

{
 "interpretations": [
   {
    "note_index": 0,
    "directive_type": "no_charge_window",
    "windows": [
       {
        "start_hour": 14,
        "end_hour": 16
       }
    ],
    "factor": null,
    "minimum_energy_kwh": null,
    "reserve_percent_of_capacity": null,
    "max_grid_kwh": null,
    "explanation": "Battery charging is disabled during this period."
   }
 ]
}

For no_op:
- windows must be null.
- unused numeric fields must be null.
"""


def _extract_json(text: str):
    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")

    return json.loads(text.strip())


def call_gemini(user_text: str) -> list[dict]:
    """
    One Gemini API call.
    Returns raw interpretation list.
    """

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise GuardrailError(
            "GEMINI_API_KEY is not set"
        )

    body = {
        "system_instruction": {
            "parts": [
                {
                    "text": SYSTEM_PROMPT
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": user_text
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        },
    }

    response = requests.post(
        GEMINI_URL.format(model=MODEL),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=TIMEOUT_S,
    )

    if response.status_code != 200:
        raise GuardrailError(
            f"Gemini HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    data = response.json()

    try:
        parts = data["candidates"][0]["content"]["parts"]

        text = "".join(
            part.get("text", "")
            for part in parts
        )

    except (KeyError, IndexError, TypeError):
        raise GuardrailError(
            f"Unexpected Gemini response: {str(data)[:300]}"
        )

    parsed = _extract_json(text)

    if isinstance(parsed, dict):
        items = parsed.get("interpretations")
    else:
        items = parsed

    if not isinstance(items, list):
        raise GuardrailError(
            "Gemini did not return interpretations list"
        )

    return items


def _user_message(notes, battery, only=None, feedback=None):

    idx = range(len(notes)) if only is None else only

    listed = "\n".join(
        f"note_index {i}: {json.dumps(notes[i])}"
        for i in idx
    )

    msg = (
        f"Battery capacity: {battery['capacity_kwh']} kWh.\n"
        f"Interpret these operator notes:\n{listed}"
    )

    if feedback:
        msg += ("\n\nYour previous answer was rejected by the validator:\n"
            + "\n".join(feedback)
            + "\nPlease correct the mistakes.")

    return msg


def _convert(raw_items, wanted, battery, entries, errors):

    by_index = {}

    for item in raw_items if isinstance(raw_items, list) else []:

        if (
            isinstance(item, dict)
            and isinstance(item.get("note_index"), int)
        ):
            by_index.setdefault(
                item["note_index"],
                item
            )

    for i in wanted:

        if i not in by_index:
            errors[i] = (
                "no interpretation returned for this note"
            )
            continue

        try:
            entries[i] = build_entry(
                by_index[i],
                i,
                battery
            )

            errors.pop(i, None)

        except GuardrailError as e:
            errors[i] = str(e)


def interpret_notes(notes, battery, llm=call_gemini):

    n = len(notes)

    entries = {}
    errors = {}

    try:

        _convert(
            llm(
                _user_message(
                    notes,
                    battery
                )
            ),
            range(n),
            battery,
            entries,
            errors
        )

    except Exception as e:

        log.warning(
            "LLM call failed: %s - %s",
            type(e).__name__,
            e
        )

        errors = {
            i: "LLM call failed"
            for i in range(n)
        }


    if errors:

        failed = sorted(errors)

        feedback = [
            f"note_index {i}: {errors[i]}"
            for i in failed
        ]

        try:

            _convert(
                llm(
                    _user_message(
                        notes,
                        battery,
                        failed,
                        feedback
                    )
                ),
                failed,
                battery,
                entries,
                errors
            )

        except Exception as e:

            log.warning(
                "LLM retry failed: %s - %s",
                type(e).__name__,
                e
            )


    for i in range(n):

        if i not in entries:

            entries[i] = no_op_entry(
                i,
                "The note could not be interpreted reliably."
            )


    result = [
        entries[i]
        for i in range(n)
    ]


    if validate_final(
        result,
        n,
        battery
    ):
        result = [
            no_op_entry(i)
            for i in range(n)
        ]


    return result