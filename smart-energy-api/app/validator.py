from app.schemas import EnergyRequest


def validate_request(request: EnergyRequest):

    if len(request.hours) != 24:
        raise ValueError(
            "Hours array must contain exactly 24 entries"
        )

    if len(request.operator_notes) < 1 or len(request.operator_notes) > 3:
        raise ValueError(
            "Operator notes must contain 1-3 items"
        )

    hours = [h.hour for h in request.hours]

    if sorted(hours) != list(range(24)):
        raise ValueError(
            "Hours must be 0-23 in order"
        )

    return True


def validate_directives(directives):

    allowed_types = {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    }

    for directive in directives:

        if directive["directive_type"] not in allowed_types:
            raise ValueError(
                "Unsupported directive type"
            )

    return True