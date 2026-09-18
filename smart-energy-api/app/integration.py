from app.services.llm_service import interpret_notes
from app.services.optimizer import optimize
from app.validator import validate_request, validate_directives


def run_pipeline(request):

    validate_request(request)

    directives = interpret_notes(
        request.operator_notes
    )

    validate_directives(
        directives
    )

    schedule = optimize(
        request,
        directives
    )

    return {
        "scenario_id": request.scenario_id,
        "directive_interpretation": directives,
        **schedule
    }