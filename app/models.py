from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class Level(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class Goal(str, Enum):
    endurance = "endurance"
    speed = "speed"
    technique = "technique"
    race_prep = "race_prep"


class PoolLength(int, Enum):
    short_course = 25
    long_course = 50


class SwimmerProfile(BaseModel):
    level: Level
    goal: Goal
    sessions_per_week: int = Field(..., ge=2, le=6)
    session_duration_minutes: int = Field(..., ge=30, le=120)
    pool_length: PoolLength = PoolLength.short_course
    stroke_focus: str = "freestyle"
    weeks: int = Field(default=4, ge=1, le=12)
    notes: Optional[str] = ""


class SetItem(BaseModel):
    description: str
    reps: int
    lengths_per_rep: int  # in pool lengths, not metres
    rest_seconds: int
    intent: str           # why this drill exists in the plan


class Session(BaseModel):
    day_label: str        # e.g. "Session 1", "Tuesday"
    total_lengths: int
    warmup: list[SetItem]
    main_set: list[SetItem]
    cooldown: list[SetItem]
    coaching_note: str    # added by the coaching agent in Step 3


class Week(BaseModel):
    week_number: int
    theme: str            # e.g. "Base Building", "Threshold", "Taper"
    intensity: str        # "low" | "moderate" | "high" | "taper"
    weekly_total_lengths: int
    sessions: list[Session]


class TrainingPlan(BaseModel):
    profile: SwimmerProfile
    summary: str
    weeks: list[Week]