"""
LLM Interpreter (Problem Statement sections 03, 04, 05.1, 08, 11).

For teammates:
    from app.services.llm_service import interpret_notes
    entries = interpret_notes(notes, battery)
`entries` is the spec-exact directive_interpretation list.
"""
from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv

from app.services.guardrails import (
    GuardrailError, build_entry, no_op_entry, validate_final,
)

load_dotenv()
log = logging.getLogger("llm_service")

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "25"))

SYSTEM_PROMPT = """You interpret campus energy operator notes for a 24-hour \
battery/solar/grid schedule (hours 0-23 of TODAY). For each note choose EXACTLY ONE directive_type:

solar_reduction          - usable rooftop solar (PV) is reduced during some hours.
                           Give "factor" = fraction of solar that REMAINS (0..1).
                           "80% reduction" -> 0.2 ; "drops to 20%" -> 0.2 ; "about 25% of forecast" -> 0.25 ;
                           "half"/"50% less" -> 0.5 ; "one-fifth of normal" -> 0.2 ; "no solar at all" -> 0.
minimum_battery_reserve  - battery must keep AT LEAST some energy stored during some hours.
                           Give "minimum_energy_kwh" if kWh is stated, OR "reserve_percent_of_capacity"
                           (0-100) if it is stated as a percentage/fraction of capacity ("half full" -> 50).
no_charge_window         - battery charging is not allowed / charger unavailable, isolated, disabled.
no_discharge_window      - battery must not discharge / not supply power / discharge disabled.
max_grid_window          - grid import/intake must not exceed X kWh per hour (feeder, transformer,
                           substation limit). Give "max_grid_kwh".
no_op                    - the note does not change TODAY's energy schedule.

no_op rules (very important):
- Unrelated topics (menus, libraries, bookings, deadlines, notices, events without an energy rule) -> no_op.
- Anything about tomorrow, next week, next month, or the past -> no_op.
- Energy-sounding notes that do not match one of the five types above (e.g. "demand will rise",
  "tariffs may change", "install new panels") -> no_op. Never invent a new type or change demand/tariffs.

Time windows:
- Return windows as start_hour and end_hour in 24-hour time. end_hour is the END time as written;
  the window covers start_hour up to but NOT including end_hour. "1 PM to 3 PM" -> start 13, end 15.
- noon = 12. midnight at the start of a window = 0; "until midnight" -> end_hour 24.
- "13:00-15:00", "from one until three" (afternoon context), "the 1-3 PM window" all -> 13..15.
- A single hour ("at 7 PM for one hour", "during the 19:00 hour") -> start 19, end 20.
- Overnight windows are fine: "10 PM to 2 AM" -> start 22, end 2.
- Use several windows only if the note truly lists separate periods.

Copy numbers exactly from the note; do not guess values that are not stated.
Write a short plain-English explanation for each note. Call the tool exactly once \
with one entry per note, using the given note_index values."""

TOOL = {
    "name": "record_interpretations",
    "description": "Record the interpretation of every operator note.",
    "input_schema": {
        "type": "object",
        "properties": {
            "interpretations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "note_index": {"type": "integer"},
                        "directive_type": {"type": "string", "enum": [
                            "solar_reduction", "minimum_battery_reserve",
                            "no_charge_window", "no_discharge_window",
                            "max_grid_window", "no_op"]},
                        "windows": {"type": "array", "items": {
                            "type": "object",
                            "properties": {
                                "start_hour": {"type": "integer"},
                                "end_hour": {"type": "integer"}},
                            "required": ["start_hour", "end_hour"]}},
                        "factor": {"type": "number"},
                        "minimum_energy_kwh": {"type": "number"},
                        "reserve_percent_of_capacity": {"type": "number"},
                        "max_grid_kwh": {"type": "number"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["note_index", "directive_type", "explanation"],
                },
            }
        },
        "required": ["interpretations"],
    },
}

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # lazy import so offline tests need no key
        _client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=1)
    return _client


def call_claude(user_text: str) -> list[dict]:
    """One LLM call. Returns the raw list of interpretations."""
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_interpretations"},
        messages=[{"role": "user", "content": user_text}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            items = block.input.get("interpretations")
            if isinstance(items, list):
                return items
    raise GuardrailError("LLM did not return interpretations")


def _user_message(notes, battery, only=None, feedback=None):
    idx = range(len(notes)) if only is None else only
    listed = "\n".join(f"note_index {i}: {json.dumps(notes[i])}" for i in idx)
    msg = (f"Battery capacity: {battery['capacity_kwh']} kWh.\n"
           f"Interpret these operator notes:\n{listed}")
    if feedback:
        msg += ("\n\nYour previous answer for these notes was rejected by the "
                "validator:\n" + "\n".join(feedback) + "\nPlease correct it.")
    return msg


def _convert(raw_items, wanted, battery, entries, errors):
    by_index = {}
    for item in raw_items if isinstance(raw_items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("note_index"), int):
            by_index.setdefault(item["note_index"], item)   # first one wins
    for i in wanted:
        if i not in by_index:
            errors[i] = "no interpretation returned for this note"
            continue
        try:
            entries[i] = build_entry(by_index[i], i, battery)
            errors.pop(i, None)
        except GuardrailError as e:
            errors[i] = str(e)


def interpret_notes(notes, battery, llm=call_claude):
    """Main entry point. Always returns one valid entry per note."""
    n = len(notes)
    entries: dict[int, dict] = {}
    errors: dict[int, str] = {}

    # Attempt 1: all notes together
    try:
        _convert(llm(_user_message(notes, battery)), range(n), battery, entries, errors)
    except Exception as e:
        log.warning("LLM call failed: %s", type(e).__name__)
        errors = {i: "LLM call failed" for i in range(n)}

    # Attempt 2: re-ask only failed notes, showing the validator errors
    if errors:
        failed = sorted(errors)
        feedback = [f"note_index {i}: {errors[i]}" for i in failed]
        try:
            _convert(llm(_user_message(notes, battery, failed, feedback)),
                     failed, battery, entries, errors)
        except Exception as e:
            log.warning("LLM retry failed: %s", type(e).__name__)

    # Safe failure: anything still invalid becomes no_op
    for i in range(n):
        if i not in entries:
            log.warning("note %d fell back to no_op: %s", i, errors.get(i))
            entries[i] = no_op_entry(
                i, "The note could not be interpreted reliably, so no directive was applied.")

    result = [entries[i] for i in range(n)]
    if validate_final(result, n, battery):      # should never happen
        result = [no_op_entry(i) for i in range(n)]
    return result