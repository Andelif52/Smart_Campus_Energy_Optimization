"""Live test with the real Claude API (uses ANTHROPIC_API_KEY from .env).
Run from project root:  python -m tests.eval_llm_live"""
import json
import time

from app.services.llm_service import interpret_notes

TOL = 0.01
SAMPLE_PATH = "sample_cases/test_inputs.json"

# Our own reworded notes, like the hidden cases will use
EXTRA = [
    ("PV production will drop to about 20% between 13:00 and 15:00.", 200,
     "solar_reduction", {"hours": [13, 14], "factor": 0.2}),
    ("Panel washing from one until three will leave roughly one-fifth of normal solar output.", 200,
     "solar_reduction", {"hours": [13, 14], "factor": 0.2}),
    ("Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window.", 200,
     "solar_reduction", {"hours": [13, 14], "factor": 0.2}),
    ("Solar will be cut in half between 9 AM and 11 AM due to haze.", 200,
     "solar_reduction", {"hours": [9, 10], "factor": 0.5}),
    ("The battery must stay at least three-quarters full from 5 PM to 8 PM.", 240,
     "minimum_battery_reserve", {"hours": [17, 18, 19], "minimum_energy_kwh": 180}),
    ("Hold a 75 kWh backup reserve between 19:00 and 21:00.", 240,
     "minimum_battery_reserve", {"hours": [19, 20], "minimum_energy_kwh": 75}),
    ("Charging is locked out from 10 PM until 1 AM for firmware updates.", 200,
     "no_charge_window", {"hours": [0, 22, 23]}),
    ("The battery cannot supply power from 4 PM to 6 PM during inverter testing.", 200,
     "no_discharge_window", {"hours": [16, 17]}),
    ("Keep grid draw under 120 kWh per hour from 8 PM until midnight.", 200,
     "max_grid_window", {"hours": [20, 21, 22, 23], "max_grid_kwh": 120}),
    ("Solar output will drop by half tomorrow afternoon.", 200, "no_op", None),
    ("Campus demand will be about 30% higher tonight because of the concert.", 200, "no_op", None),
    ("The IT department is replacing printers on the third floor.", 200, "no_op", None),
]


def same(got, exp_type, exp_adj):
    if got["directive_type"] != exp_type:
        return False
    a = got["structured_adjustment"]
    if exp_adj is None or a is None:
        return a == exp_adj
    if a.get("hours") != exp_adj.get("hours") or set(a) != set(exp_adj):
        return False
    return all(abs(a[k] - exp_adj[k]) <= TOL for k in a if k != "hours")


def report(label, note, got, exp_type, exp_adj):
    ok = same(got, exp_type, exp_adj)
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"      note:     {note}")
        print(f"      expected: {exp_type} {exp_adj}")
        print(f"      got:      {got['directive_type']} {got['structured_adjustment']}")
    return ok


def main():
    passed = total = 0
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    print("--- public sample cases ---")
    for case in cases:
        inp = case["input"]
        t = time.time()
        got = interpret_notes(inp["operator_notes"], inp["battery"])
        dt = time.time() - t
        for g, e, note in zip(got, case["expected_output"]["directive_interpretation"],
                              inp["operator_notes"]):
            total += 1
            passed += report(f"{case['id']} note {e['note_index']} ({dt:.1f}s)",
                             note, g, e["directive_type"], e["structured_adjustment"])

    print("\n--- paraphrase tests ---")
    for note, cap, t, adj in EXTRA:
        got = interpret_notes([note], {"capacity_kwh": cap})[0]
        total += 1
        passed += report(note[:60], note, got, t, adj)

    print(f"\n{passed}/{total} notes interpreted correctly")


if __name__ == "__main__":
    main()