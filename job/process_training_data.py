import json
import os
import sys
import boto3
from botocore.exceptions import ClientError
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

NEBIUS_API_KEY = os.environ["NEBIUS_API_KEY"]
TOKENFACTORY_BASE_URL = os.getenv(
    "TOKENFACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"
)
MODEL_ID = os.getenv("MODEL_ID", "meta-llama/Llama-3.3-70B-Instruct")

S3_ENDPOINT_URL = os.getenv(
    "S3_ENDPOINT_URL", "https://storage.eu-north1.nebius.cloud"
)
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]
S3_BUCKET = os.getenv("S3_BUCKET", "swimcoach-knowledge")
S3_KEY = "knowledge_base.json"

SEED_PATH = os.path.join(os.path.dirname(__file__), "seed_data", "training_principles.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")


def get_client() -> OpenAI:
    return OpenAI(api_key=NEBIUS_API_KEY, base_url=TOKENFACTORY_BASE_URL)


def enrich_profile(client: OpenAI, profile: dict) -> str:
    prompt = f"""You are a swimming coach educator. Write a concise coaching summary
(3–5 sentences) for an AI planning tool to use when generating training plans.

Profile:
- Level: {profile['level']}
- Goal: {profile['goal']}
- Volume per session: {profile['volume_per_session_lengths']['min']}–{profile['volume_per_session_lengths']['max']} lengths (25m pool)
- Intensity: {profile['intensity_distribution']['z1_aerobic_pct']}% aerobic / {profile['intensity_distribution']['z2_threshold_pct']}% threshold / {profile['intensity_distribution']['z3_speed_pct']}% speed / {profile['intensity_distribution']['drill_technique_pct']}% drills
- Periodization: {profile['periodization']['pattern']}
- Rep lengths: {profile['rep_length_range'][0]}–{profile['rep_length_range'][1]} lengths per rep
- Key drills: {', '.join(d['name'] for d in profile['recommended_drills'])}
- Key principles: {'; '.join(profile['key_principles'])}

Write the summary in plain English. Include: appropriate volume range, intensity balance,
periodization approach, and 1–2 most important principles. Be specific and technical.
Do not use bullet points. Output the summary only, no preamble."""

    response = client.chat.completions.create(
        model=MODEL_ID,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()


def upload_to_s3(content: str) -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )

    # Create bucket if it doesn't exist
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        print(f"  Bucket '{S3_BUCKET}' exists")
    except ClientError:
        print(f"  Creating bucket '{S3_BUCKET}'...")
        s3.create_bucket(Bucket=S3_BUCKET)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=S3_KEY,
        Body=content.encode("utf-8"),
        ContentType="application/json",
    )
    print(f"  Uploaded to s3://{S3_BUCKET}/{S3_KEY}")


def main() -> None:
    print("SwimCoach AI — Data Processing Job")
    print("=" * 40)

    # Load seed data
    print(f"\n[1/3] Loading seed data from {SEED_PATH}")
    with open(SEED_PATH) as f:
        seed = json.load(f)
    profiles = seed["profiles"]
    print(f"  {len(profiles)} profiles loaded")

    # Enrich each profile
    print(f"\n[2/3] Enriching profiles via TokenFactory ({MODEL_ID})")
    client = get_client()
    knowledge_base = {
        "version": seed["version"],
        "description": seed["description"],
        "generated_by": f"swimcoach-data-job / {MODEL_ID}",
        "zones": seed["zones"],
        "profiles": {},
    }

    for i, profile in enumerate(profiles):
        key = f"{profile['level']}_{profile['goal']}"
        print(f"  [{i + 1}/{len(profiles)}] {key}...")

        summary = enrich_profile(client, profile)
        knowledge_base["profiles"][key] = {
            **profile,
            "coaching_summary": summary,
        }
        print(f"    → {summary[:80]}...")

    # Save locally
    output = json.dumps(knowledge_base, indent=2)
    with open(OUTPUT_PATH, "w") as f:
        f.write(output)
    print(f"\n  Saved locally: {OUTPUT_PATH}")

    # Upload to Object Storage
    print(f"\n[3/3] Uploading to Nebius Object Storage")
    upload_to_s3(output)

    print("\n✓ Job complete")
    print(f"  Profiles processed: {len(knowledge_base['profiles'])}")
    print(f"  Output: s3://{S3_BUCKET}/{S3_KEY}")


if __name__ == "__main__":
    main()
