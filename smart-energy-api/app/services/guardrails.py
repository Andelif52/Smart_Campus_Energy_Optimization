"""
Guardrail Validator (Problem Statement sections 04, 05.1, 08).
The LLM returns simple raw fields; this module checks them, expands time
windows (start inclusive, end exclusive), converts percent reserves to kWh,
and builds the exact structured_adjustment shape. It can never invent a type.
"""
from __future__ import annotations
import math

ALLOWED_TYPES = {
    "solar_reduction", "minimum_battery_reserve", "no_charge_window",
    "no_discharge_window", "max_grid_window", "no_op",
}


class GuardrailError(ValueError):
    pass


def _finite_number(value, name):
    if isinstance(value, bool):
        raise GuardrailError(f"{name} must be a number, got boolean")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise GuardrailError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(x):
        raise GuardrailError(f"{name} must be finite")
    return x


def _hour_value(value, name):
    x = _finite_number(value, name)
    if x != int(x):
        raise GuardrailError(f"{name} must be a whole hour, got {value!r}")
    x = int(x)
    if not 0 <= x <= 24:
        raise GuardrailError(f"{name} must be between 0 and 24, got {x}")
    return x


def expand_window(start, end):
    """Start-inclusive, end-exclusive. 24 = midnight at end of day.
    If end <= start the window crosses midnight (22 -> 2 = 22,23,0,1)."""
    start = _hour_value(start, "start_hour") % 24
    end = _hour_value(end, "end_hour")
    if end != 24 and end <= start:
        return list(range(start, 24)) + list(range(0, end))
    return list(range(start, end))


def hours_from_raw(raw):
    hours = set()
    windows = raw.get("windows")
    if windows:
        if not isinstance(windows, list):
            raise GuardrailError("windows must be a list")
        for w in windows:
            if not isinstance(w, dict):
                raise GuardrailError("each window must be an object")
            hours.update(expand_window(w.get("start_hour"), w.get("end_hour")))
    elif raw.get("hours") is not None:
        if not isinstance(raw["hours"], list):
            raise GuardrailError("hours must be a list")
        for h in raw["hours"]:
            v = _hour_value(h, "hour")
            if v == 24:
                raise GuardrailError("hour 24 is not a valid hour")
            hours.add(v)
    if not hours:
        raise GuardrailError("directive has no hours")
    return sorted(hours)


def no_op_entry(index, explanation=None):
    return {
        "note_index": index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": explanation
        or "This note does not affect today's 24-hour energy schedule.",
    }


def build_entry(raw, index, battery):
    """Convert one raw LLM interpretation into a spec-exact entry."""
    if not isinstance(raw, dict):
        raise GuardrailError("interpretation must be an object")

    dtype = raw.get("directive_type")
    if dtype not in ALLOWED_TYPES:
        raise GuardrailError(f"unsupported directive_type {dtype!r}")

    explanation = str(raw.get("explanation") or "").strip()[:300]
    if dtype == "no_op":
        return no_op_entry(index, explanation or None)

    hours = hours_from_raw(raw)
    capacity = float(battery["capacity_kwh"])

    if dtype == "solar_reduction":
        factor = _finite_number(raw.get("factor"), "factor")
        if not 0.0 <= factor <= 1.0:
            raise GuardrailError(f"factor must be in [0, 1], got {factor}")
        adj = {"hours": hours, "factor": round(factor, 6)}

    elif dtype == "minimum_battery_reserve":
        if raw.get("minimum_energy_kwh") is not None:
            kwh = _finite_number(raw["minimum_energy_kwh"], "minimum_energy_kwh")
        elif raw.get("reserve_percent_of_capacity") is not None:
            pct = _finite_number(raw["reserve_percent_of_capacity"],
                                 "reserve_percent_of_capacity")
            if not 0.0 <= pct <= 100.0:
                raise GuardrailError("reserve percent must be 0..100")
            kwh = capacity * pct / 100.0
        else:
            raise GuardrailError("reserve directive needs kWh or percent")
        if kwh < 0 or kwh > capacity + 1e-9:
            raise GuardrailError(f"reserve {kwh} outside 0..capacity {capacity}")
        adj = {"hours": hours, "minimum_energy_kwh": round(kwh, 6)}

    elif dtype == "max_grid_window":
        cap = _finite_number(raw.get("max_grid_kwh"), "max_grid_kwh")
        if cap < 0:
            raise GuardrailError("max_grid_kwh must be non-negative")
        adj = {"hours": hours, "max_grid_kwh": round(cap, 6)}

    else:  # no_charge_window / no_discharge_window
        adj = {"hours": hours}

    return {
        "note_index": index,
        "applies": True,
        "directive_type": dtype,
        "structured_adjustment": adj,
        "explanation": explanation or f"Interpreted as {dtype}.",
    }


EXPECTED_KEYS = {
    "solar_reduction": {"hours", "factor"},
    "minimum_battery_reserve": {"hours", "minimum_energy_kwh"},
    "no_charge_window": {"hours"},
    "no_discharge_window": {"hours"},
    "max_grid_window": {"hours", "max_grid_kwh"},
}


def validate_final(entries, n_notes, battery):
    """Last check on the finished list. Empty list = everything valid."""
    problems = []
    if [e.get("note_index") for e in entries] != list(range(n_notes)):
        problems.append("entries must cover note_index 0..N-1 exactly once, in order")
    for e in entries:
        t, adj, i = e.get("directive_type"), e.get("structured_adjustment"), e.get("note_index")
        if t not in ALLOWED_TYPES:
            problems.append(f"note {i}: bad type {t!r}")
            continue
        if t == "no_op":
            if e.get("applies") is not False or adj is not None:
                problems.append(f"note {i}: no_op needs applies=false, adjustment=null")
            continue
        if e.get("applies") is not True or not isinstance(adj, dict):
            problems.append(f"note {i}: {t} needs applies=true and an object")
            continue
        hrs = adj.get("hours")
        if (not isinstance(hrs, list) or not hrs or hrs != sorted(set(hrs))
                or any(not isinstance(h, int) or not 0 <= h <= 23 for h in hrs)):
            problems.append(f"note {i}: hours must be unique ascending ints 0..23")
        if set(adj) != EXPECTED_KEYS[t]:
            problems.append(f"note {i}: keys must be exactly {sorted(EXPECTED_KEYS[t])}")
    return problems