from fastapi import FastAPI, HTTPException
from app.schemas import EnergyRequest
from app.integration import run_pipeline
from app.schemas import EnergyRequest, EnergyResponse


app = FastAPI(
    title="Smart Campus Energy Optimizer"
)


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
        print("DEBUG ERROR:", e)   # visible only in server console
        
        raise HTTPException(
            status_code=500,
            detail="Internal processing error"
        )