import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

TOKENFACTORY_BASE_URL = os.getenv(
    "TOKENFACTORY_BASE_URL",
    "https://api.tokenfactory.us-central1.nebius.com/v1",
)
MODEL_ID = os.getenv("MODEL_ID", "meta-llama/Llama-3.3-70B-Instruct")
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")

def get_client() -> AsyncOpenAI:
    if not NEBIUS_API_KEY:
        raise EnvironmentError(
            "NEBIUS_API_KEY is not set."
        )
    return AsyncOpenAI(
        api_key=NEBIUS_API_KEY,
        base_url=TOKENFACTORY_BASE_URL,
    )