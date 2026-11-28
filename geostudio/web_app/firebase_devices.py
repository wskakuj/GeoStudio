"""Pseudonymous per-computer identifier for the official desktop client.

This is not hardware attestation or DRM. A privileged local user can
modify or clone a machine identifier. No raw machine GUID leaves the PC.
"""
import hashlib
import os
from pathlib import Path


def device_id(project_id: str) -> str:
    try:
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
        else:
            value = Path("/etc/machine-id").read_text(encoding="ascii").strip()
        if not isinstance(value, str) or not 8 <= len(value.strip()) <= 128:
            return ""
        material = ("GeoStudio-device-v1:" + project_id + ":" + value.strip().lower())
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
    except (OSError, ValueError, UnicodeError):
        return ""
