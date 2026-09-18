from fastapi import FastAPI, HTTPException
from app.schemas import EnergyRequest
from app.integration import run_pipeline

app = FastAPI(
    title="Smart Campus Energy Optimizer"
)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/optimize-energy")
def optimize_energy(
    request: EnergyRequest
):

    try:
        result = run_pipeline(request)

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Internal processing error"
        )