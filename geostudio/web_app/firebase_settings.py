"""Build-time Firebase client configuration (no service account credentials).

Keep the tracked template empty. The release builder must supply the actual
project's public client configuration before freezing GeoStudio. A frozen
client never accepts environment overrides.
"""
PROJECT_ID = ""
WEB_API_KEY = ""
