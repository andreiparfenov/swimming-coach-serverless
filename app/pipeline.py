import json
import re
from app.llm import get_client, MODEL_ID
from app.models import SwimmerProfile, TrainingPlan, Week, Session, SetItem
from app.knowledge import get_coaching_summary


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def run_periodization_agent(profile: SwimmerProfile) -> dict:
    client = get_client()

    taper_rule = (
        "The FINAL week must be a taper: theme='Taper', intensity='taper', volume_multiplier=0.7."
        if profile.goal.value == "race_prep"
        else ""
    )

    grounding = get_coaching_summary(profile.level.value, profile.goal.value)
    grounding_block = (
        f"\nEstablished coaching guidance for this swimmer type:\n{grounding}\n"
        if grounding
        else ""
    )

    response = await client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {
                "role": "system",
                "content": "You are an expert swimming coach. Output only valid JSON, nothing else.",
            },
            {
                "role": "user",
                "content": f"""Design a {profile.weeks}-week periodization structure for:
- Level: {profile.level.value}
- Goal: {profile.goal.value.replace("_", " ")}
- Sessions/week: {profile.sessions_per_week}
- Session duration: {profile.session_duration_minutes} min
- Pool: {profile.pool_length.value}m
- Stroke: {profile.stroke_focus}
- Notes: {profile.notes or "none"}
{grounding_block}
{taper_rule}

Rules:
- volume_multiplier: 0.85–1.2 (1.0 = baseline)
- intensity: "low" | "moderate" | "high" | "taper"
- Beginner: max intensity "moderate"
- Apply progressive overload; include a deload (volume_multiplier ≤ 0.9) every 3–4 weeks
- Use specific theme names: "Aerobic Base", "Threshold Development", "Speed Endurance", "Race Pace", "Recovery", "Taper"
- Follow the established coaching guidance above where provided — it reflects real periodization practice for this swimmer type

Return ONLY this JSON:
{{"weeks": [{{"week_number": 1, "theme": "Aerobic Base", "intensity": "low", "volume_multiplier": 1.0}}]}}""",
            },
        ],
        temperature=0.2,
        max_tokens=600,
    )

    raw = _clean_json(response.choices[0].message.content)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Step 1 JSON parse failed: {e}\nRaw: {raw[:500]}")


async def run_session_agent(profile: SwimmerProfile, macro: dict) -> list[dict]:
    client = get_client()

    base_lengths = int(profile.session_duration_minutes * 0.7)

    set_length_guidance = {
        "beginner": "Keep reps short: 2–4 lengths per rep.",
        "intermediate": "Use moderate rep lengths: 4–6 lengths per rep.",
        "advanced": "Can use longer reps: 4–8 lengths per rep.",
    }[profile.level.value]

    grounding = get_coaching_summary(profile.level.value, profile.goal.value)
    grounding_note = (
        f"\nReference coaching context: {grounding}\n" if grounding else ""
    )

    schema = (
        '{"sessions": [{"day_label": "Session 1", "total_lengths": 40, '
        '"warmup": [{"description": "Easy freestyle", "reps": 4, "lengths_per_rep": 2, '
        '"rest_seconds": 20, "intent": "Establish rhythm"}], '
        '"main_set": [{"description": "Freestyle pull", "reps": 6, "lengths_per_rep": 4, '
        '"rest_seconds": 30, "intent": "Build aerobic base"}], '
        '"cooldown": [{"description": "Easy backstroke", "reps": 4, "lengths_per_rep": 1, '
        '"rest_seconds": 0, "intent": "Recover"}], "coaching_note": ""}]}'
    )

    weeks = []
    for week_data in macro["weeks"]:
        vol = max(20, int(base_lengths * week_data["volume_multiplier"]))

        response = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert swimming coach. Output only valid JSON, nothing else.",
                },
                {
                    "role": "user",
                    "content": f"""Generate {profile.sessions_per_week} training sessions for Week {week_data["week_number"]}.

Week context:
- Theme: {week_data["theme"]}
- Intensity: {week_data["intensity"]}
- Target volume per session: ~{vol} lengths (1 length = {profile.pool_length.value}m)
- Swimmer: {profile.level.value}, goal = {profile.goal.value.replace("_", " ")}
- Stroke focus: {profile.stroke_focus}
{grounding_note}
Rules:
- Distances in LENGTHS only, never metres
- total_lengths = sum of (reps × lengths_per_rep) across all three phases
- Warmup: ~20% of volume, easy effort, rest_seconds 15–20
- Main set: ~65% of volume, theme-appropriate effort
- Cooldown: ~15% of volume, easy effort, rest_seconds 0
- rest_seconds: 15–20 easy / 30–45 moderate / 45–90 high intensity
- Vary sessions across the week — no two sessions identical
- Include at least one drill or technique set per session (e.g. catch-up drill, fist drill, kick set)
- {set_length_guidance}
- Leave coaching_note as ""

Return ONLY valid JSON matching this schema exactly:
{schema}""",
                },
            ],
            temperature=0.45,
            max_tokens=4000,
        )

        raw = _clean_json(response.choices[0].message.content)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Step 2 JSON parse failed (week {week_data['week_number']}): {e}\nRaw: {raw[:500]}")
        for session in parsed["sessions"]:
            session["total_lengths"] = sum(
                s["reps"] * s["lengths_per_rep"]
                for phase in ["warmup", "main_set", "cooldown"]
                for s in session[phase]
            )
        weekly_total = sum(s["total_lengths"] for s in parsed["sessions"])

        weeks.append({
            **week_data,
            "sessions": parsed["sessions"],
            "weekly_total_lengths": weekly_total,
        })

    return weeks


async def run_coaching_agent(profile: SwimmerProfile, weeks: list[dict]) -> list[dict]:
    client = get_client()

    sessions_summary = []
    for week in weeks:
        for session in week["sessions"]:
            sessions_summary.append({
                "week": week["week_number"],
                "theme": week["theme"],
                "intensity": week["intensity"],
                "session": session["day_label"],
                "total_lengths": session["total_lengths"],
                "main_focus": [s["description"] for s in session["main_set"]],
            })

    total_sessions = sum(len(w["sessions"]) for w in weeks)

    response = await client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {
                "role": "system",
                "content": "You are an expert swimming coach. Output only valid JSON, nothing else.",
            },
            {
                "role": "user",
                "content": f"""Write a coaching note for each session below.

Swimmer: {profile.level.value}, goal = {profile.goal.value.replace("_", " ")}, stroke = {profile.stroke_focus}, pool = {profile.pool_length.value}m

Each note MUST:
- Be 2-3 sentences
- Reference the week theme and what this session trains
- Include a specific underwater dolphin kick cue (e.g. "Hold your streamline and fire 4–5 dolphin kicks off every wall before surfacing.")
- Include one technique cue appropriate for a {profile.level.value} swimmer
- Be encouraging and specific, not generic

Sessions:
{json.dumps(sessions_summary, indent=2)}

Return ONLY this JSON with exactly {total_sessions} notes in order:
{{"notes": ["note for session 1", "note for session 2"]}}""",
            },
        ],
        temperature=0.5,
        max_tokens=2500,
    )

    raw = _clean_json(response.choices[0].message.content)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Step 3 JSON parse failed: {e}\nRaw: {raw[:500]}")
    notes = parsed["notes"]

    note_idx = 0
    for week in weeks:
        for session in week["sessions"]:
            if note_idx < len(notes):
                session["coaching_note"] = notes[note_idx]
                note_idx += 1

    return weeks


async def generate_plan(profile: SwimmerProfile) -> TrainingPlan:
    macro = await run_periodization_agent(profile)
    weeks_raw = await run_session_agent(profile, macro)
    weeks_enriched = await run_coaching_agent(profile, weeks_raw)

    weeks = [
        Week(
            week_number=w["week_number"],
            theme=w["theme"],
            intensity=w["intensity"],
            weekly_total_lengths=w["weekly_total_lengths"],
            sessions=[Session(**s) for s in w["sessions"]],
        )
        for w in weeks_enriched
    ]

    return TrainingPlan(
        profile=profile,
        summary=(
            f"{profile.weeks}-week {profile.goal.value.replace('_', ' ')} plan "
            f"for a {profile.level.value} swimmer, "
            f"{profile.sessions_per_week}×/week in a {profile.pool_length.value}m pool."
        ),
        weeks=weeks,
    )