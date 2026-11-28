"""Build-time Firebase client configuration (no service account credentials).

Keep the tracked template empty. The release builder must supply the actual
project's public client configuration through build.ps1 before freezing
GeoStudio. The builder restores this tracked template. A frozen client
never accepts environment overrides.
"""
PROJECT_ID = ""
WEB_API_KEY = ""
OFFLINE_URL = ""
OFFLINE_PUBLIC_KEY = ""

ADMIN_URL = ""
