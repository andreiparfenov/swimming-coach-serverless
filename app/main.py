from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models import SwimmerProfile, TrainingPlan
from app.pipeline import generate_plan

app = FastAPI(
    title="Swimming coach",
    description=(
        "POST a swimmer profile, get back a structured multi-week training plan."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tighten to your frontend URL before production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/generate-plan", response_model=TrainingPlan)
async def create_plan(profile: SwimmerProfile):
    try:
        plan = await generate_plan(profile)
        return plan
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")