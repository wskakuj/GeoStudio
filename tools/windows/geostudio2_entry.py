"""Frozen GeoStudio 2.0 Windows entry point (FastAPI + WebView2 only)."""
import sys

from geostudio.web_app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
