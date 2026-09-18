from app.services.llm_service import interpret_notes
from app.services.optimizer import optimize


def run_pipeline(request):

    directives = interpret_notes(
        request.operator_notes
    )


    schedule = optimize(
        request,
        directives
    )


    response = {
        "scenario_id": request.scenario_id,
        "directive_interpretation": directives,
        **schedule
    }

    return response