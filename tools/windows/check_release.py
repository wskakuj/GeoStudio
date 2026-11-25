"""Fail before publishing an installer whose source version differs from its tag."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import tomllib


def _assignment(path: Path, name: str) -> str:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name
                   for target in node.targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    return value
    raise ValueError(f"{path}: missing version assignment {name}")


def _inno_version(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Missing Inno Setup metadata matching {pattern}")
    return match.group(1)


def check_source(root: Path, tag: str) -> str:
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not match:
        raise ValueError(f"Invalid release tag: {tag!r}; expected vX.Y.Z")
    expected = match.group(1)
    with (root / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    inno = (root / "tools/windows/geostudio2.iss").read_text(encoding="utf-8")
    values = {
        "pyproject.toml": version,
        "geostudio/__init__.py": _assignment(root / "geostudio/__init__.py", "__version__"),
        "updater.py fallback": _assignment(root / "geostudio/web_app/updater.py", "FALLBACK_VERSION"),
        "Inno AppVersion": _inno_version(inno, r'^#define MyAppVersion "([^"]+)"\s*$'),
        "Inno output filename": _inno_version(inno, r'^OutputBaseFilename=GeoStudio2-Setup-([\d.]+)-x64\s*$'),
        "Inno file version": _inno_version(inno, r'^VersionInfoVersion=([\d.]+)\.0\s*$'),
    }
    for name, actual in values.items():
        if actual != expected:
            raise ValueError(f"{name}: {actual!r} does not match tag {tag!r}")
    return expected


if __name__ == "__main__":
    try:
        print(check_source(Path(__file__).resolve().parents[2], sys.argv[1]))
    except (OSError, ValueError, KeyError, IndexError, SyntaxError) as error:
        sys.exit(f"Release version validation failed: {error}")
