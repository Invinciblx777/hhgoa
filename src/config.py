"""Loads configuration from the .env file at the repository root.

Values are read once at import time. Any key that is missing or empty raises a
RuntimeError naming the offending keys, so a misconfigured environment fails
immediately instead of part-way through the pipeline.
"""

import os

from dotenv import load_dotenv

load_dotenv()

REQUIRED_KEYS = (
    "SERPAPI_KEY",
    "IMGBB_KEY",
    "AMOY_RPC_URL",
    "PRIVATE_KEY",
    "CONTRACT_ADDRESS",
)

_missing = [key for key in REQUIRED_KEYS if not os.getenv(key)]
if _missing:
    raise RuntimeError(
        "Missing required .env key(s): "
        + ", ".join(_missing)
        + ". Copy .env.example to .env and fill in every value."
    )

SERPAPI_KEY: str = os.environ["SERPAPI_KEY"]
IMGBB_KEY: str = os.environ["IMGBB_KEY"]
AMOY_RPC_URL: str = os.environ["AMOY_RPC_URL"]
PRIVATE_KEY: str = os.environ["PRIVATE_KEY"]
CONTRACT_ADDRESS: str = os.environ["CONTRACT_ADDRESS"]
