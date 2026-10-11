"""Published Android app and self-hosted interface updates.

The gateway serves the latest APK and a small release manifest from the data
directory. A newer native build is installed from the APK. A newer interface
bundle is described for Expo Updates and for the in-app launch check.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from nanobot.security.runtime_storage import get_config_path

APK_NAME = "kili.apk"
BUNDLE_NAME = "bundle.js"
HERMES_BUNDLE_NAME = "bundle.hbc"
RELEASE_NAME = "release.json"


def packaged_release() -> Path:
    return Path(__file__).resolve().parents[2] / "deploy" / "mobile-release"


def published_bundle(directory: Path) -> Path | None:
    for name in (HERMES_BUNDLE_NAME, BUNDLE_NAME):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _release_ready(path: Path) -> bool:
    return (path / APK_NAME).is_file() or published_bundle(path) is not None


def release_root() -> Path:
    """Prefer files published on the server, then the copy shipped with the source."""
    data = get_config_path().parent / "mobile-release"
    if _release_ready(data):
        return data
    packaged = packaged_release()
    if _release_ready(packaged):
        return packaged
    return data


def update_action(version_code: int, bundle_revision: int, remote: dict[str, Any]) -> str | None:
    """Return apk, bundle, or nothing. A native bump wins over an interface bundle."""
    remote_code = remote.get("version_code")
    remote_bundle = remote.get("bundle_revision")
    if not isinstance(remote_code, int) or not isinstance(remote_bundle, int):
        return None
    if remote_code > version_code:
        return "apk"
    if remote_code == version_code and remote_bundle > bundle_revision:
        return "bundle"
    return None


def read_release(root: Path | None = None) -> dict[str, Any]:
    directory = root or release_root()
    path = directory / RELEASE_NAME
    payload: dict[str, Any] = {
        "native_version": "0.1.0",
        "version_code": 1,
        "bundle_revision": 0,
        "runtime_version": "0.1.0",
        "update_id": "",
        "notes": "",
        "apk_url": "/downloads/kili.apk",
        "bundle_url": "/api/mobile/bundle",
        "apk_available": (directory / APK_NAME).is_file(),
        "bundle_available": published_bundle(directory) is not None,
    }
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in ("native_version", "version_code", "bundle_revision", "runtime_version", "update_id", "notes"):
                if key in raw:
                    payload[key] = raw[key]
    payload["apk_available"] = (directory / APK_NAME).is_file()
    payload["bundle_available"] = published_bundle(directory) is not None
    return payload


def asset_hash(data: bytes) -> str:
    """Expo Updates launch-asset hash: unpadded base64url SHA-256."""
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


def expo_update_body(release: dict[str, Any], bundle: bytes, asset_url: str, current_id: str | None,
                     asset_key: str = "bundle.js") -> tuple[int, bytes, str]:
    """Return status, body, and content type for the Expo Updates protocol."""
    update_id = release.get("update_id")
    if not isinstance(update_id, str) or not update_id or current_id == update_id:
        return 204, b"", "text/plain"
    manifest: dict[str, Any] = {
        "id": update_id,
        "createdAt": "2026-10-11T00:00:00.000Z",
        "runtimeVersion": release.get("runtime_version") or "0.1.0",
        "launchAsset": {
            "hash": asset_hash(bundle),
            "key": asset_key,
            "contentType": "application/javascript",
            "url": asset_url,
        },
        "assets": [],
        "metadata": {},
        "extra": {"bundleRevision": release.get("bundle_revision")},
    }
    boundary = "kili-update"
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n"
        f"{json.dumps(manifest, separators=(',', ':'))}\r\n--{boundary}--\r\n"
    ).encode()
    return 200, body, f'multipart/mixed; boundary="{boundary}"'
