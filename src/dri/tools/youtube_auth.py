"""
One-time YouTube OAuth2 authentication — obtains a refresh token.

Usage:
    uv run python src/dri/tools/youtube_auth.py

What it does:
  1. Reads credentials/youtube_oauth_client.json (OAuth2 Desktop App credentials).
  2. Opens a browser tab — you log in with the Google account that owns DRI Studio.
  3. Google redirects to localhost — the script captures the code automatically.
  4. Exchanges the code for tokens and writes YOUTUBE_REFRESH_TOKEN into .env.

Run this once. The refresh token never expires unless you revoke the app access.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Resolve project root (two levels up from this file: tools/ → dri/ → src/ → project)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_CLIENT_SECRET_FILE = _PROJECT_ROOT / "credentials" / "youtube_oauth_client.json"
_ENV_FILE = _PROJECT_ROOT / ".env"

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> None:
    if not _CLIENT_SECRET_FILE.exists():
        print(f"[ERROR] Client secret not found: {_CLIENT_SECRET_FILE}")
        print("Download it from Google Cloud Console → Credentials → your OAuth 2.0 Client ID → Download JSON")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[ERROR] google-auth-oauthlib is not installed.")
        print("Run: uv sync")
        sys.exit(1)

    print("Opening browser for YouTube authorization...")
    print("Log in with the Google account that owns the DRI Studio channel.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRET_FILE), scopes=_SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=True)

    refresh_token = credentials.refresh_token
    if not refresh_token:
        print("[ERROR] No refresh token received. Make sure you authorized the app.")
        sys.exit(1)

    print(f"\nRefresh token obtained: {refresh_token[:20]}...\n")

    # Write into .env — replace placeholder or existing value
    if _ENV_FILE.exists():
        env_text = _ENV_FILE.read_text(encoding="utf-8")
        new_line = f"YOUTUBE_REFRESH_TOKEN={refresh_token}"
        if re.search(r"^YOUTUBE_REFRESH_TOKEN=", env_text, re.MULTILINE):
            env_text = re.sub(
                r"^YOUTUBE_REFRESH_TOKEN=.*$", new_line, env_text, flags=re.MULTILINE
            )
        else:
            env_text += f"\n{new_line}\n"
        _ENV_FILE.write_text(env_text, encoding="utf-8")
        print(f"YOUTUBE_REFRESH_TOKEN written to {_ENV_FILE}")
    else:
        print(f"[WARNING] .env not found. Add this line manually:\n{new_line}")


if __name__ == "__main__":
    main()
