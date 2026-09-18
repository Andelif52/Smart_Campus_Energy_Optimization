"""Offline tests with a fake LLM. Run from project root:  python -m pytest tests/test_llm.py -v"""
import pytest

from app.services.guardrails import validate_final
from app.services.llm_service import interpret_notes

W = lambda s, e: [{"start_hour": s, "end_hour": e}]
BAT = {"capacity_kwh": 200}


def fake_llm(raws):
    def llm(_msg):
        return [dict(r, note_index=i, explanation="x") for i, r in enumerate(raws)]
    return llm


def pairs(entries):
    return [(e["directive_type"], e["structured_adjustment"]) for e in entries]


@pytest.mark.parametrize("raw, expected", [
    (dict(directive_type="solar_reduction", windows=W(12, 14), factor=0.25),
     ("solar_reduction", {"hours": [12, 13], "factor": 0.25})),
    (dict(directive_type="no_charge_window", windows=W(2, 5)),
     ("no_charge_window", {"hours": [2, 3, 4]})),
    (dict(directive_type="minimum_battery_reserve", windows=W(18, 21), reserve_percent_of_capacity=50),
     ("minimum_battery_reserve", {"hours": [18, 19, 20], "minimum_energy_kwh": 100})),
    (dict(directive_type="no_discharge_window", windows=W(18, 20)),
     ("no_discharge_window", {"hours": [18, 19]})),
    (dict(directive_type="max_grid_window", windows=W(18, 21), max_grid_kwh=155),
     ("max_grid_window", {"hours": [18, 19, 20], "max_grid_kwh": 155})),
    (dict(directive_type="no_charge_window", windows=W(22, 2)),
     ("no_charge_window", {"hours": [0, 1, 22, 23]})),
    (dict(directive_type="max_grid_window", windows=W(20, 24), max_grid_kwh=120),
     ("max_grid_window", {"hours": [20, 21, 22, 23], "max_grid_kwh": 120})),
    (dict(directive_type="no_op"), ("no_op", None)),
])
def test_conversion(raw, expected):
    got = interpret_notes(["note"], BAT, fake_llm([raw]))
    assert pairs(got) == [expected]
    assert validate_final(got, 1, BAT) == []


def test_no_op_shape():
    e = interpret_notes(["x"], BAT, fake_llm([dict(directive_type="no_op")]))[0]
    assert e["applies"] is False and e["structured_adjustment"] is None


def test_retry_fixes_bad_factor():
    calls = []
    def llm(msg):
        calls.append(msg)
        f = 1.8 if len(calls) == 1 else 0.2
        return [dict(note_index=0, directive_type="solar_reduction",
                     windows=W(13, 15), factor=f, explanation="x")]
    got = interpret_notes(["n"], BAT, llm)
    assert pairs(got) == [("solar_reduction", {"hours": [13, 14], "factor": 0.2})]
    assert "rejected by the validator" in calls[1]


def test_invented_type_becomes_no_op():
    got = interpret_notes(["n"], BAT, fake_llm([dict(directive_type="demand_increase", windows=W(1, 2))]))
    assert pairs(got) == [("no_op", None)]


def test_reserve_above_capacity_becomes_no_op():
    got = interpret_notes(["n"], BAT, fake_llm([dict(directive_type="minimum_battery_reserve",
                                                     windows=W(1, 3), minimum_energy_kwh=999)]))
    assert pairs(got) == [("no_op", None)]


def test_llm_crash_is_safe():
    def boom(_msg):
        raise RuntimeError("network down")
    got = interpret_notes(["a", "b"], BAT, boom)
    assert pairs(got) == [("no_op", None), ("no_op", None)]


def test_missing_and_duplicate_notes():
    def messy(msg):
        if "rejected" in msg:
            return [dict(note_index=1, directive_type="no_op", explanation="x")]
        return [dict(note_index=0, directive_type="no_charge_window", windows=W(1, 2), explanation="x"),
                dict(note_index=0, directive_type="no_op", explanation="dup")]
    got = interpret_notes(["a", "b"], BAT, messy)
    assert [e["note_index"] for e in got] == [0, 1]
    assert pairs(got) == [("no_charge_window", {"hours": [1]}), ("no_op", None)]