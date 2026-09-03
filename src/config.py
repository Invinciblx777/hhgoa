"""Loads configuration from the .env file at the repository root.

Keys are validated on first access rather than at import, so a module only
fails on the keys it actually uses. PROJECT_SPEC requires every module to run
standalone from its __main__ block; validating all five keys at import time
would make M3 and M4 unrunnable until the M5 chain keys exist, which is the
opposite of that. Accessing a missing or empty key still raises RuntimeError
naming it, so a misconfigured environment fails loudly and immediately.
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


def __getattr__(name: str) -> str:
    """Resolve a config key on attribute access. See PEP 562."""
    if name not in REQUIRED_KEYS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required .env key: {name}. "
            f"Copy .env.example to .env and fill in the value."
        )
    return value


def missing_keys() -> list[str]:
    """Return the required keys that are absent or empty, in declared order."""
    return [key for key in REQUIRED_KEYS if not os.getenv(key)]


if __name__ == "__main__":
    absent = missing_keys()
    for key in REQUIRED_KEYS:
        print(f"  {key:<18} {'MISSING' if key in absent else 'set'}")
    print(f"\n{len(REQUIRED_KEYS) - len(absent)}/{len(REQUIRED_KEYS)} keys set")
