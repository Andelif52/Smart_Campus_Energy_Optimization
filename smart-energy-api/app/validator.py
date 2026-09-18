from app.schemas import EnergyRequest


ALLOWED_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}


def validate_request(request: EnergyRequest):

    if len(request.hours) != 24:
        raise ValueError(
            "Hours array must contain exactly 24 entries"
        )

    if len(request.operator_notes) < 1:
        raise ValueError(
            "Operator notes must contain at least 1 item"
        )

    if len(request.operator_notes) > 3:
        raise ValueError(
            "Operator notes must contain at most 3 items"
        )

    hours = [h.hour for h in request.hours]

    if sorted(hours) != list(range(24)):
        raise ValueError(
            "Hours must contain exactly 0-23"
        )

    # Check for negative physical values
    for hour in request.hours:

        if hour.demand_kwh < 0:
            raise ValueError(
                f"Negative demand at hour {hour.hour}"
            )

        if hour.solar_kwh < 0:
            raise ValueError(
                f"Negative solar at hour {hour.hour}"
            )

        if hour.tariff_bdt_per_kwh < 0:
            raise ValueError(
                f"Negative tariff at hour {hour.hour}"
            )

    battery = request.battery

    if battery.capacity_kwh < 0:
        raise ValueError(
            "Battery capacity cannot be negative"
        )

    if battery.initial_energy_kwh < 0:
        raise ValueError(
            "Initial battery energy cannot be negative"
        )

    if (
        battery.initial_energy_kwh
        > battery.capacity_kwh
    ):
        raise ValueError(
            "Initial battery energy exceeds capacity"
        )

    if battery.minimum_energy_kwh < 0:
        raise ValueError(
            "Minimum battery energy cannot be negative"
        )

    if (
        battery.minimum_energy_kwh
        > battery.capacity_kwh
    ):
        raise ValueError(
            "Minimum battery energy exceeds capacity"
        )

    if battery.max_charge_kwh_per_hour < 0:
        raise ValueError(
            "Maximum charge rate cannot be negative"
        )

    if battery.max_discharge_kwh_per_hour < 0:
        raise ValueError(
            "Maximum discharge rate cannot be negative"
        )

    return True


def validate_directives(directives):

    if not isinstance(directives, list):
        raise ValueError(
            "Directives must be a list"
        )

    if len(directives) == 0:
        raise ValueError(
            "At least one directive interpretation is required"
        )

    if len(directives) > 3:
        raise ValueError(
            "At most 3 directive interpretations are allowed"
        )

    for expected_index, directive in enumerate(directives):

        if not isinstance(directive, dict):
            raise ValueError(
                "Each directive must be a dictionary"
            )

        # -------------------------------------------------
        # Required fields
        # -------------------------------------------------

        required_fields = {
            "note_index",
            "applies",
            "directive_type",
            "structured_adjustment",
            "explanation"
        }

        missing = (
            required_fields
            - set(directive.keys())
        )

        if missing:
            raise ValueError(
                f"Directive is missing fields: "
                f"{sorted(missing)}"
            )

        # -------------------------------------------------
        # note_index
        # -------------------------------------------------

        if directive["note_index"] != expected_index:
            raise ValueError(
                "Directive note_index values must "
                "match operator note order"
            )

        # -------------------------------------------------
        # applies
        # -------------------------------------------------

        if not isinstance(
            directive["applies"],
            bool
        ):
            raise ValueError(
                "Directive applies must be boolean"
            )

        directive_type = directive[
            "directive_type"
        ]

        # -------------------------------------------------
        # directive type
        # -------------------------------------------------

        if directive_type not in ALLOWED_DIRECTIVE_TYPES:
            raise ValueError(
                f"Unsupported directive type: "
                f"{directive_type}"
            )

        adjustment = directive[
            "structured_adjustment"
        ]

        # -------------------------------------------------
        # no_op
        # -------------------------------------------------

        if directive_type == "no_op":

            if directive["applies"]:
                raise ValueError(
                    "no_op must have applies=false"
                )

            if adjustment is not None:
                raise ValueError(
                    "no_op must have "
                    "structured_adjustment=null"
                )

            continue

        # -------------------------------------------------
        # Every real directive must apply
        # -------------------------------------------------

        if not directive["applies"]:
            raise ValueError(
                f"{directive_type} must have applies=true"
            )

        if not isinstance(adjustment, dict):
            raise ValueError(
                f"{directive_type} requires "
                "structured_adjustment"
            )

        # -------------------------------------------------
        # Hours
        # -------------------------------------------------

        if "hours" not in adjustment:
            raise ValueError(
                f"{directive_type} requires hours"
            )

        hours = adjustment["hours"]

        if not isinstance(hours, list):
            raise ValueError(
                "Directive hours must be a list"
            )

        if len(hours) == 0:
            raise ValueError(
                "Directive hours cannot be empty"
            )

        if any(
            not isinstance(h, int)
            for h in hours
        ):
            raise ValueError(
                "Directive hours must contain integers"
            )

        if any(
            h < 0 or h > 23
            for h in hours
        ):
            raise ValueError(
                "Directive hours must be between 0 and 23"
            )

        if len(hours) != len(set(hours)):
            raise ValueError(
                "Directive hours must be unique"
            )

        if hours != sorted(hours):
            raise ValueError(
                "Directive hours must be in ascending order"
            )

        # -------------------------------------------------
        # Solar reduction
        # -------------------------------------------------

        if directive_type == "solar_reduction":

            if "factor" not in adjustment:
                raise ValueError(
                    "solar_reduction requires factor"
                )

            factor = adjustment["factor"]

            if not isinstance(
                factor,
                (int, float)
            ):
                raise ValueError(
                    "solar reduction factor must be numeric"
                )

            if factor < 0 or factor > 1:
                raise ValueError(
                    "solar reduction factor must "
                    "be between 0 and 1"
                )

        # -------------------------------------------------
        # Minimum reserve
        # -------------------------------------------------

        elif directive_type == "minimum_battery_reserve":

            if "minimum_energy_kwh" not in adjustment:
                raise ValueError(
                    "minimum_battery_reserve requires "
                    "minimum_energy_kwh"
                )

            reserve = adjustment[
                "minimum_energy_kwh"
            ]

            if not isinstance(
                reserve,
                (int, float)
            ):
                raise ValueError(
                    "minimum battery reserve must be numeric"
                )

            if reserve < 0:
                raise ValueError(
                    "minimum battery reserve cannot be negative"
                )

        # -------------------------------------------------
        # No charge / no discharge
        # -------------------------------------------------

        elif directive_type in {
            "no_charge_window",
            "no_discharge_window"
        }:

            # No extra fields required.
            pass

        # -------------------------------------------------
        # Maximum grid
        # -------------------------------------------------

        elif directive_type == "max_grid_window":

            if "max_grid_kwh" not in adjustment:
                raise ValueError(
                    "max_grid_window requires "
                    "max_grid_kwh"
                )

            max_grid = adjustment[
                "max_grid_kwh"
            ]

            if not isinstance(
                max_grid,
                (int, float)
            ):
                raise ValueError(
                    "max_grid_kwh must be numeric"
                )

            if max_grid < 0:
                raise ValueError(
                    "max_grid_kwh cannot be negative"
                )

    return True