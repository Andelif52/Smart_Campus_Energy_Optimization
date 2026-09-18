from app.services.optimizer import optimize
from app.schemas import EnergyRequest, Hour, Battery


def make_basic_request():

    hours = []

    for h in range(24):

        hours.append(
            Hour(
                hour=h,
                demand_kwh=100,
                solar_kwh=0,
                tariff_bdt_per_kwh=5
            )
        )

    battery = Battery(
        capacity_kwh=200,
        initial_energy_kwh=100,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100
    )

    return EnergyRequest(
        scenario_id="TEST-01",
        operator_notes=[],
        hours=hours,
        battery=battery
    )


def test_basic_optimization():

    request = make_basic_request()

    result = optimize(
        request,
        []
    )

    assert len(result["hourly_plan"]) == 24

    assert result["total_grid_kwh"] >= 0

    assert result["total_cost_bdt"] >= 0

    assert result["peak_grid_kwh"] >= 0

def test_energy_balance():
    request = make_basic_request()

    result = optimize(request, [])

    for h, plan in enumerate(result["hourly_plan"]):

        demand = request.hours[h].demand_kwh

        grid = plan["grid_kwh"]
        solar = plan["solar_used_kwh"]

        if plan["battery_action"] == "charge":
            battery_flow = plan["battery_kwh"]
        elif plan["battery_action"] == "discharge":
            battery_flow = -plan["battery_kwh"]
        else:
            battery_flow = 0

        # grid + solar - battery_flow = demand
        calculated_demand = grid + solar - battery_flow

        assert abs(calculated_demand - demand) <= 0.01


def test_end_of_day_neutrality():
    request = make_basic_request()

    result = optimize(request, [])

    final_energy = result["hourly_plan"][-1][
        "battery_energy_after_kwh"
    ]

    assert abs(
        final_energy - request.battery.initial_energy_kwh
    ) <= 0.01


def test_battery_energy_limits():
    request = make_basic_request()

    result = optimize(request, [])

    for plan in result["hourly_plan"]:

        energy = plan["battery_energy_after_kwh"]

        assert energy >= request.battery.minimum_energy_kwh - 0.01

        assert energy <= request.battery.capacity_kwh + 0.01


def test_solar_reduction():

    request = make_basic_request()

    # Give hour 10 some solar.
    request.hours[10].solar_kwh = 100

    directive = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {
            "hours": [10],
            "factor": 0.5
        },
        "explanation": "Solar output is reduced."
    }

    # Convert dictionary to a simple object
    class Directive:
        pass

    d = Directive()

    d.note_index = directive["note_index"]
    d.applies = directive["applies"]
    d.directive_type = directive["directive_type"]
    d.structured_adjustment = directive["structured_adjustment"]
    d.explanation = directive["explanation"]

    result = optimize(request, [d])

    solar_used = result["hourly_plan"][10]["solar_used_kwh"]

    assert solar_used <= 50.01


def test_no_charge_window():

    request = make_basic_request()

    # Make hour 5 very cheap so normally the optimizer
    # would have an incentive to charge.
    request.hours[5].tariff_bdt_per_kwh = 1
    request.hours[6].tariff_bdt_per_kwh = 20

    class Directive:
        pass

    d = Directive()
    d.note_index = 0
    d.applies = True
    d.directive_type = "no_charge_window"
    d.structured_adjustment = {
        "hours": [5]
    }
    d.explanation = "Charging is not allowed."

    result = optimize(request, [d])

    plan = result["hourly_plan"][5]

    assert plan["battery_action"] != "charge"


def test_no_discharge_window():

    request = make_basic_request()

    request.hours[5].tariff_bdt_per_kwh = 20

    class Directive:
        pass

    d = Directive()
    d.note_index = 0
    d.applies = True
    d.directive_type = "no_discharge_window"
    d.structured_adjustment = {
        "hours": [5]
    }
    d.explanation = "Discharging is not allowed."

    result = optimize(request, [d])

    plan = result["hourly_plan"][5]

    assert plan["battery_action"] != "discharge"


def test_max_grid_window():

    request = make_basic_request()

    # Make hour 10 demand exceed the cap.
    request.hours[10].demand_kwh = 100

    class Directive:
        pass

    d = Directive()
    d.note_index = 0
    d.applies = True
    d.directive_type = "max_grid_window"
    d.structured_adjustment = {
        "hours": [10],
        "max_grid_kwh": 80
    }
    d.explanation = "Grid import is capped."

    result = optimize(request, [d])

    grid = result["hourly_plan"][10]["grid_kwh"]

    assert grid <= 80.01


def test_no_op():

    request = make_basic_request()

    class Directive:
        pass

    d = Directive()
    d.note_index = 0
    d.applies = False
    d.directive_type = "no_op"
    d.structured_adjustment = None
    d.explanation = "No operational adjustment."

    result = optimize(request, [d])

    assert len(result["hourly_plan"]) == 24    

def test_battery_shifts_energy_to_expensive_hour():

    hours = []

    for h in range(24):

        # Normal hours
        tariff = 5

        # Cheap hour
        if h == 5:
            tariff = 1

        # Expensive hour
        if h == 18:
            tariff = 20

        hours.append(
            Hour(
                hour=h,
                demand_kwh=100,
                solar_kwh=0,
                tariff_bdt_per_kwh=tariff
            )
        )

    battery = Battery(
        capacity_kwh=150,
        initial_energy_kwh=50,
        minimum_energy_kwh=0,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50
    )

    request = EnergyRequest(
        scenario_id="BATTERY-TEST-01",
        operator_notes=[],
        hours=hours,
        battery=battery
    )

    result = optimize(request, [])

    cheap_hour = result["hourly_plan"][5]
    expensive_hour = result["hourly_plan"][18]

    # Battery should charge during the cheap hour.
    assert cheap_hour["battery_action"] == "charge"

    # Battery should discharge during the expensive hour.
    assert expensive_hour["battery_action"] == "discharge"

    # Energy should be shifted from the cheap hour
    # to the expensive hour.
    assert cheap_hour["battery_kwh"] > 0
    assert expensive_hour["battery_kwh"] > 0 

def test_minimum_battery_reserve():

    request = make_basic_request()

    class Directive:
        pass

    d = Directive()

    d.note_index = 0
    d.applies = True
    d.directive_type = "minimum_battery_reserve"
    d.structured_adjustment = {
        "hours": [18, 19, 20],
        "minimum_energy_kwh": 120
    }
    d.explanation = "Battery reserve must remain at least 120 kWh."

    result = optimize(request, [d])

    for h in [18, 19, 20]:

        energy = result["hourly_plan"][h][
            "battery_energy_after_kwh"
        ]

        assert energy >= 119.99

def test_multiple_directives():

    hours = []

    for h in range(24):

        solar = 0
        tariff = 5

        # Solar during hours 10 and 11
        if h in [10, 11]:
            solar = 100

        # Expensive period
        if h in [18, 19, 20]:
            tariff = 20

        hours.append(
            Hour(
                hour=h,
                demand_kwh=100,
                solar_kwh=solar,
                tariff_bdt_per_kwh=tariff
            )
        )

    battery = Battery(
        capacity_kwh=200,
        initial_energy_kwh=100,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100
    )

    request = EnergyRequest(
        scenario_id="MULTI-TEST-01",
        operator_notes=[],
        hours=hours,
        battery=battery
    )

    # Create directives
    class Directive:
        pass

    solar_directive = Directive()
    solar_directive.note_index = 0
    solar_directive.applies = True
    solar_directive.directive_type = "solar_reduction"
    solar_directive.structured_adjustment = {
        "hours": [10, 11],
        "factor": 0.5
    }
    solar_directive.explanation = "Solar output is reduced."

    no_charge_directive = Directive()
    no_charge_directive.note_index = 1
    no_charge_directive.applies = True
    no_charge_directive.directive_type = "no_charge_window"
    no_charge_directive.structured_adjustment = {
        "hours": [14, 15]
    }
    no_charge_directive.explanation = "Battery charging is not allowed."

    no_discharge_directive = Directive()
    no_discharge_directive.note_index = 2
    no_discharge_directive.applies = True
    no_discharge_directive.directive_type = "no_discharge_window"
    no_discharge_directive.structured_adjustment = {
        "hours": [18]
    }
    no_discharge_directive.explanation = "Battery discharge is not allowed."

    result = optimize(
        request,
        [
            solar_directive,
            no_charge_directive,
            no_discharge_directive
        ]
    )

    # -----------------------------
    # Check solar reduction
    # -----------------------------

    assert result["hourly_plan"][10]["solar_used_kwh"] <= 50.01
    assert result["hourly_plan"][11]["solar_used_kwh"] <= 50.01

    # -----------------------------
    # Check no-charge window
    # -----------------------------

    assert result["hourly_plan"][14]["battery_action"] != "charge"
    assert result["hourly_plan"][15]["battery_action"] != "charge"

    # -----------------------------
    # Check no-discharge window
    # -----------------------------

    assert result["hourly_plan"][18]["battery_action"] != "discharge"

    # -----------------------------
    # Check complete schedule
    # -----------------------------

    assert len(result["hourly_plan"]) == 24

    # -----------------------------
    # Check final battery neutrality
    # -----------------------------

    final_energy = result["hourly_plan"][23][
        "battery_energy_after_kwh"
    ]

    assert abs(
        final_energy - battery.initial_energy_kwh
    ) <= 0.01        

def test_reserve_and_grid_cap_together():

    hours = []

    for h in range(24):

        tariff = 5

        if h in [19, 20]:
            tariff = 20

        hours.append(
            Hour(
                hour=h,
                demand_kwh=100,
                solar_kwh=0,
                tariff_bdt_per_kwh=tariff
            )
        )

    battery = Battery(
        capacity_kwh=200,
        initial_energy_kwh=150,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100
    )

    request = EnergyRequest(
        scenario_id="MULTI-TEST-02",
        operator_notes=[],
        hours=hours,
        battery=battery
    )

    class Directive:
        pass

    reserve = Directive()
    reserve.note_index = 0
    reserve.applies = True
    reserve.directive_type = "minimum_battery_reserve"
    reserve.structured_adjustment = {
        "hours": [18, 19, 20, 21],
        "minimum_energy_kwh": 120
    }
    reserve.explanation = "Battery reserve must remain at least 120 kWh."

    grid_cap = Directive()
    grid_cap.note_index = 1
    grid_cap.applies = True
    grid_cap.directive_type = "max_grid_window"
    grid_cap.structured_adjustment = {
        "hours": [19, 20],
        "max_grid_kwh": 80
    }
    grid_cap.explanation = "Grid import is capped."

    result = optimize(
        request,
        [reserve, grid_cap]
    )

    # Grid cap
    assert result["hourly_plan"][19]["grid_kwh"] <= 80.01
    assert result["hourly_plan"][20]["grid_kwh"] <= 80.01

    # Reserve
    for h in [18, 19, 20, 21]:

        energy = result["hourly_plan"][h][
            "battery_energy_after_kwh"
        ]

        assert energy >= 119.99

    # Final neutrality
    final_energy = result["hourly_plan"][23][
        "battery_energy_after_kwh"
    ]

    assert abs(
        final_energy - battery.initial_energy_kwh
    ) <= 0.01    

def test_infeasible_grid_cap():

    hours = []

    for h in range(24):

        hours.append(
            Hour(
                hour=h,
                demand_kwh=100,
                solar_kwh=0,
                tariff_bdt_per_kwh=5
            )
        )

    # Battery is empty and cannot discharge.
    battery = Battery(
        capacity_kwh=100,
        initial_energy_kwh=50,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=0,
        max_discharge_kwh_per_hour=0
    )

    request = EnergyRequest(
        scenario_id="INFEASIBLE-01",
        operator_notes=[],
        hours=hours,
        battery=battery
    )

    class Directive:
        pass

    d = Directive()

    d.note_index = 0
    d.applies = True
    d.directive_type = "max_grid_window"
    d.structured_adjustment = {
        "hours": [10],
        "max_grid_kwh": 50
    }
    d.explanation = "Grid import cannot exceed 50 kWh."

    # The hour requires 100 kWh of demand,
    # but grid is limited to 50 and the battery/solar
    # cannot provide the remaining 50.
    try:

        optimize(request, [d])

        assert False, (
            "Optimizer should reject an infeasible scenario."
        )

    except ValueError:
        pass    

    