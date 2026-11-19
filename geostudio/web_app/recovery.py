"""Crash-safe, checksum-bound local recovery for native WebView2 sessions.

Never writes to the user's source MAP. Recovery snapshots are stored under
%LOCALAPPDATA%/GeoStudio2/recovery or the platform equivalent. Both map and
topology are verified before a candidate is offered or restored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
import json
import os
import re
import tempfile

MAX_RECOVERY_MAP=80*1024*1024
MAX_RECOVERY_TOPOLOGY=2*1024*1024


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _atomic_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".geostudio-recovery-",suffix=".tmp",
                             dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


class LocalRecoveryStore:
    """One verified active snapshot per opened, physically selected source MAP."""

    def __init__(self, directory: Path):
        self.directory=Path(directory)

    @staticmethod
    def _key(source: Path) -> str:
        return _digest(str(source.resolve()).casefold().encode("utf-8"))[:24]

    def _index(self,source: Path) -> Path:
        return self.directory/(self._key(source)+".json")

    def _metadata(self,source: Path) -> dict | None:
        try:
            manifest=json.loads(self._index(source).read_bytes())
        except (OSError,ValueError,UnicodeDecodeError):
            return None
        if (not isinstance(manifest,dict) or
                set(manifest)!={"format","sourceHash","mapHash","topologyHash",
                                 "mapFile","topologyFile","savedAt","revision"} or
                manifest["format"]!="geostudio-recovery-v1" or
                any(not isinstance(manifest[field],str) or
                    not re.fullmatch(r"[0-9a-f]{64}",manifest[field])
                    for field in ("sourceHash","mapHash","topologyHash")) or
                type(manifest["revision"]) is not int or
                not 0<=manifest["revision"]<1000000):
            return None
        key=self._key(source)
        for field,suffix in (("mapFile",".MAP"),
                             ("topologyFile",".json")):
            value=manifest[field]
            if (not isinstance(value,str) or
                    not re.fullmatch(re.escape(key)+
                      r"\.[0-9a-f]{16}"+re.escape(suffix),value)):
                return None
        return manifest

    def load(self,source: Path,source_bytes: bytes) -> tuple[dict,bytes,bytes] | None:
        """Validate a complete candidate against the unmodified source file."""
        manifest=self._metadata(source)
        if manifest is None or manifest["sourceHash"]!=_digest(source_bytes):
            return None
        try:
            map_path=self.directory/manifest["mapFile"]
            topo_path=self.directory/manifest["topologyFile"]
            if (not 0<map_path.stat().st_size<=MAX_RECOVERY_MAP or
                    not 0<topo_path.stat().st_size<=MAX_RECOVERY_TOPOLOGY):
                return None
            map_bytes=map_path.read_bytes()
            topology_bytes=topo_path.read_bytes()
        except OSError:
            return None
        if (_digest(map_bytes)!=manifest["mapHash"] or
                _digest(topology_bytes)!=manifest["topologyHash"]):
            return None
        return manifest,map_bytes,topology_bytes

    def candidate(self,source: Path,source_bytes: bytes) -> dict | None:
        recovery=self.load(source,source_bytes)
        if recovery is None:return None
        manifest,map_bytes,topology=recovery
        return {"available":True,"savedAt":manifest["savedAt"],
                "revision":manifest["revision"],
                "bytes":len(map_bytes)}

    def save(self,source: Path,source_bytes: bytes,
             map_bytes: bytes,topology_bytes: bytes,revision: int) -> dict:
        if (not isinstance(source_bytes,bytes) or not source_bytes or
                not 0<len(map_bytes)<=MAX_RECOVERY_MAP or
                not 0<len(topology_bytes)<=MAX_RECOVERY_TOPOLOGY or
                type(revision) is not int or not 0<=revision<1000000):
            raise ValueError("Nieprawidłowe dane zapisu awaryjnego.")
        self.directory.mkdir(parents=True,exist_ok=True)
        prefix=self._key(source)
        nonce=token_hex(8)
        map_name=f"{prefix}.{nonce}.MAP"
        topo_name=f"{prefix}.{nonce}.json"
        previous=self._metadata(source)
        manifest={
            "format":"geostudio-recovery-v1",
            "sourceHash":_digest(source_bytes),
            "mapHash":_digest(map_bytes),
            "topologyHash":_digest(topology_bytes),
            "mapFile":map_name,
            "topologyFile":topo_name,
            "savedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "revision":revision,
        }
        try:
            _atomic_new(self.directory/map_name,map_bytes)
            _atomic_new(self.directory/topo_name,topology_bytes)
            _atomic_new(self._index(source),
                        json.dumps(manifest,separators=(",",":")).encode())
        except Exception:
            # The old manifest continues to be authoritative until replaced.
            for name in (map_name,topo_name):
                try:(self.directory/name).unlink()
                except OSError:pass
            raise
        if previous:
            for field in ("mapFile","topologyFile"):
                if previous[field] not in (map_name,topo_name):
                    try:(self.directory/previous[field]).unlink()
                    except OSError:pass
        return {"saved":True,"revision":revision,
                "bytes":len(map_bytes),"savedAt":manifest["savedAt"]}
