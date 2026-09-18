from fastapi import FastAPI, HTTPException

from app.schemas import EnergyRequest, EnergyResponse
from app.integration import run_pipeline


app = FastAPI(
    title="Smart Campus Energy Optimizer",
    description="AI-assisted campus energy optimization API",
    version="1.0.0"
)


@app.get("/")
def root():
    return {
        "message": "Smart Campus Energy Optimization API is running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/optimize-energy", response_model=EnergyResponse)
def optimize_energy(
    request: EnergyRequest
):
    try:
        result = run_pipeline(request)

        return result

    except Exception as e:
        print("DEBUG ERROR:", e)

        raise HTTPException(
            status_code=500,
            detail="Internal processing error"
        )