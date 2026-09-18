import numpy as np
from scipy.optimize import linprog


# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------

HOURS = 24

G_START = 0
S_START = 24
B_START = 48
E_START = 72

N = 96


# ---------------------------------------------------------
# Helper
# ---------------------------------------------------------

def get_directive_value(directive, key, default=None):
    """
    Supports dictionary directives and object-style directives.
    The real pipeline uses dictionaries, but supporting both
    keeps the optimizer compatible with existing tests.
    """

    if isinstance(directive, dict):
        return directive.get(key, default)

    return getattr(directive, key, default)


# ---------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------

def optimize(request, directives):

    # -----------------------------------------------------
    # 1. Validate basic input
    # -----------------------------------------------------

    if len(request.hours) != HOURS:
        raise ValueError(
            "Exactly 24 hourly entries are required."
        )

    hours = sorted(
        request.hours,
        key=lambda h: h.hour
    )

    if [h.hour for h in hours] != list(range(HOURS)):
        raise ValueError(
            "Hours must contain exactly 0 through 23."
        )

    battery = request.battery

    demand = [
        float(h.demand_kwh)
        for h in hours
    ]

    solar = [
        float(h.solar_kwh)
        for h in hours
    ]

    tariff = [
        float(h.tariff_bdt_per_kwh)
        for h in hours
    ]

    # -----------------------------------------------------
    # 2. Prepare directive effects
    # -----------------------------------------------------

    solar_factor = [1.0] * HOURS

    minimum_reserve = [
        float(battery.minimum_energy_kwh)
        for _ in range(HOURS)
    ]

    no_charge = [False] * HOURS
    no_discharge = [False] * HOURS

    max_grid = [None] * HOURS

    allowed_types = {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    }

    # -----------------------------------------------------
    # 3. Apply directives
    # -----------------------------------------------------

    for directive in directives:

        applies = get_directive_value(
            directive,
            "applies",
            False
        )

        directive_type = get_directive_value(
            directive,
            "directive_type"
        )

        adjustment = get_directive_value(
            directive,
            "structured_adjustment",
            None
        ) or {}

        if not applies:
            continue

        if directive_type not in allowed_types:
            raise ValueError(
                f"Unsupported directive type: {directive_type}"
            )

        directive_hours = adjustment.get(
            "hours",
            []
        )

        # ---------------------------------------------
        # Solar reduction
        # ---------------------------------------------

        if directive_type == "solar_reduction":

            factor = adjustment.get("factor")

            if factor is None:
                raise ValueError(
                    "solar_reduction requires factor."
                )

            for h in directive_hours:
                solar_factor[h] *= float(factor)

        # ---------------------------------------------
        # Minimum battery reserve
        # ---------------------------------------------

        elif directive_type == "minimum_battery_reserve":

            reserve = adjustment.get(
                "minimum_energy_kwh"
            )

            if reserve is None:
                raise ValueError(
                    "minimum_battery_reserve requires "
                    "minimum_energy_kwh."
                )

            reserve = float(reserve)

            for h in directive_hours:
                minimum_reserve[h] = max(
                    minimum_reserve[h],
                    reserve
                )

        # ---------------------------------------------
        # No charging
        # ---------------------------------------------

        elif directive_type == "no_charge_window":

            for h in directive_hours:
                no_charge[h] = True

        # ---------------------------------------------
        # No discharging
        # ---------------------------------------------

        elif directive_type == "no_discharge_window":

            for h in directive_hours:
                no_discharge[h] = True

        # ---------------------------------------------
        # Maximum grid import
        # ---------------------------------------------

        elif directive_type == "max_grid_window":

            limit = adjustment.get(
                "max_grid_kwh"
            )

            if limit is None:
                raise ValueError(
                    "max_grid_window requires "
                    "max_grid_kwh."
                )

            limit = float(limit)

            for h in directive_hours:

                if max_grid[h] is None:
                    max_grid[h] = limit

                else:
                    max_grid[h] = min(
                        max_grid[h],
                        limit
                    )

        # ---------------------------------------------
        # No operation
        # ---------------------------------------------

        elif directive_type == "no_op":
            continue

    # -----------------------------------------------------
    # 4. Effective solar
    # -----------------------------------------------------

    effective_solar = []

    for h in range(HOURS):

        available = (
            solar[h] * solar_factor[h]
        )

        effective_solar.append(
            max(0.0, available)
        )

    # -----------------------------------------------------
    # 5. Objective
    #
    # Minimize:
    #
    #     sum(grid[h] * tariff[h])
    # -----------------------------------------------------

    c = np.zeros(N)

    for h in range(HOURS):

        c[G_START + h] = tariff[h]

    # -----------------------------------------------------
    # 6. Equality constraints
    # -----------------------------------------------------

    A_eq = []
    b_eq = []

    # -----------------------------------------------------
    # Energy balance
    #
    # grid + solar - battery_flow = demand
    #
    # Positive battery_flow = charge
    # Negative battery_flow = discharge
    # -----------------------------------------------------

    for h in range(HOURS):

        row = np.zeros(N)

        row[G_START + h] = 1
        row[S_START + h] = 1
        row[B_START + h] = -1

        A_eq.append(row)
        b_eq.append(demand[h])

    # -----------------------------------------------------
    # Battery state
    #
    # E[0] - b[0] = initial_energy
    # -----------------------------------------------------

    row = np.zeros(N)

    row[E_START] = 1
    row[B_START] = -1

    A_eq.append(row)
    b_eq.append(
        float(battery.initial_energy_kwh)
    )

    # -----------------------------------------------------
    # Battery state for remaining hours
    #
    # E[h] - E[h-1] - b[h] = 0
    # -----------------------------------------------------

    for h in range(1, HOURS):

        row = np.zeros(N)

        row[E_START + h] = 1
        row[E_START + h - 1] = -1
        row[B_START + h] = -1

        A_eq.append(row)
        b_eq.append(0)

    # -----------------------------------------------------
    # End-of-day neutrality
    #
    # E[23] = initial_energy
    # -----------------------------------------------------

    row = np.zeros(N)

    row[E_START + 23] = 1

    A_eq.append(row)
    b_eq.append(
        float(battery.initial_energy_kwh)
    )

    # -----------------------------------------------------
    # 7. Variable bounds
    # -----------------------------------------------------

    bounds = []

    # -----------------------------------------------------
    # Grid
    # -----------------------------------------------------

    for h in range(HOURS):

        if max_grid[h] is not None:

            bounds.append(
                (0, max_grid[h])
            )

        else:

            bounds.append(
                (0, None)
            )

    # -----------------------------------------------------
    # Solar
    # -----------------------------------------------------

    for h in range(HOURS):

        bounds.append(
            (0, effective_solar[h])
        )

    # -----------------------------------------------------
    # Battery flow
    # -----------------------------------------------------

    for h in range(HOURS):

        min_flow = -float(
            battery.max_discharge_kwh_per_hour
        )

        max_flow = float(
            battery.max_charge_kwh_per_hour
        )

        if no_charge[h]:
            max_flow = 0

        if no_discharge[h]:
            min_flow = 0

        bounds.append(
            (min_flow, max_flow)
        )

    # -----------------------------------------------------
    # Battery energy
    # -----------------------------------------------------

    for h in range(HOURS):

        bounds.append(
            (
                minimum_reserve[h],
                float(battery.capacity_kwh)
            )
        )

    # -----------------------------------------------------
    # 8. Run optimizer
    # -----------------------------------------------------

    result = linprog(
        c,
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        bounds=bounds,
        method="highs"
    )

    # -----------------------------------------------------
    # 9. Handle infeasible problem
    # -----------------------------------------------------

    if not result.success:

        raise ValueError(
            f"Energy optimization failed: "
            f"{result.message}"
        )

    x = result.x

    # -----------------------------------------------------
    # 10. Extract variables
    # -----------------------------------------------------

    grid = x[
        G_START:G_START + HOURS
    ]

    solar_used = x[
        S_START:S_START + HOURS
    ]

    battery_flow = x[
        B_START:B_START + HOURS
    ]

    battery_energy = x[
        E_START:E_START + HOURS
    ]

    # -----------------------------------------------------
    # 11. Build hourly plan
    # -----------------------------------------------------

    hourly_plan = []

    tolerance = 1e-7

    for h in range(HOURS):

        flow = float(
            battery_flow[h]
        )

        if flow > tolerance:

            battery_action = "charge"
            battery_kwh = flow

        elif flow < -tolerance:

            battery_action = "discharge"
            battery_kwh = abs(flow)

        else:

            battery_action = "idle"
            battery_kwh = 0.0

        hourly_plan.append(
            {
                "hour": hours[h].hour,

                "grid_kwh": round(
                    float(grid[h]),
                    6
                ),

                "solar_used_kwh": round(
                    float(solar_used[h]),
                    6
                ),

                "battery_action":
                    battery_action,

                "battery_kwh": round(
                    battery_kwh,
                    6
                ),

                "battery_energy_after_kwh":
                    round(
                        float(battery_energy[h]),
                        6
                    )
            }
        )

    # -----------------------------------------------------
    # 12. Calculate totals
    # -----------------------------------------------------

    total_grid_kwh = sum(
        plan["grid_kwh"]
        for plan in hourly_plan
    )

    total_cost_bdt = sum(
        hourly_plan[h]["grid_kwh"]
        * tariff[h]
        for h in range(HOURS)
    )

    peak_grid_kwh = max(
        plan["grid_kwh"]
        for plan in hourly_plan
    )

    # -----------------------------------------------------
    # 13. Summary
    # -----------------------------------------------------

    charging_hours = sum(
        1
        for plan in hourly_plan
        if plan["battery_action"] == "charge"
    )

    discharging_hours = sum(
        1
        for plan in hourly_plan
        if plan["battery_action"] == "discharge"
    )

    plan_summary = (
        f"Optimized 24-hour energy schedule with "
        f"{charging_hours} charging hours and "
        f"{discharging_hours} discharging hours. "
        f"Total grid import is "
        f"{total_grid_kwh:.2f} kWh and total "
        f"energy cost is "
        f"{total_cost_bdt:.2f} BDT."
    )

    # -----------------------------------------------------
    # 14. Return
    # -----------------------------------------------------

    return {
        "hourly_plan": hourly_plan,

        "total_grid_kwh": round(
            total_grid_kwh,
            6
        ),

        "total_cost_bdt": round(
            total_cost_bdt,
            6
        ),

        "peak_grid_kwh": round(
            peak_grid_kwh,
            6
        ),

        "plan_summary": plan_summary
    }