"""Write the temporary client configuration for a Windows preview build.

The PowerShell builder restores the tracked template in a finally block.
Never log the key, accept executable text, or load a service account file.
"""
from pathlib import Path
import os

from geostudio.web_app.firebase_auth import AuthError, FirebaseConfig


def render_config(project_id, api_key, offline_url="", offline_public_key=""):
    config = FirebaseConfig(project_id.strip(), api_key.strip(),
                            offline_url.strip(), offline_public_key.strip())
    return ("# Generated for this build only. Do not commit.\n"
            f"PROJECT_ID = {config.project_id!r}\n"
            f"WEB_API_KEY = {config.api_key!r}\n"
            f"OFFLINE_URL = {config.offline_url!r}\n"
            f"OFFLINE_PUBLIC_KEY = {config.offline_public_key!r}\n")


def main():
    try:
        text = render_config(os.environ.get("GEOSTUDIO_FIREBASE_PROJECT_ID", ""),
                             os.environ.get("GEOSTUDIO_FIREBASE_WEB_API_KEY", ""),
                             os.environ.get("GEOSTUDIO_OFFLINE_URL", ""),
                             os.environ.get("GEOSTUDIO_OFFLINE_PUBLIC_KEY", ""))
    except AuthError:
        return 1
    target = Path(__file__).resolve().parents[2] / "geostudio/web_app/firebase_settings.py"
    target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
