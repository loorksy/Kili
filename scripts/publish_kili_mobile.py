#!/usr/bin/env python3
"""Publish the Android app and interface bundle into Kili's data directory.

Interface-only changes bump bundle_revision and copy the exported JavaScript.
A native change bumps version_code and copies the release APK. The gateway
serves both from the same host the owner already uses.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import uuid
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Kili's Android release files")
    parser.add_argument("--dest", type=Path, required=True, help="Directory the gateway reads, usually /opt/kili/data/mobile-release")
    parser.add_argument("--mobile", type=Path, default=Path(__file__).resolve().parents[1] / "mobile")
    parser.add_argument("--apk", type=Path, help="Built release APK to publish")
    parser.add_argument("--bundle", type=Path, help="Exported JavaScript bundle to publish")
    parser.add_argument("--export", action="store_true", help="Run npx expo export --platform android before copying the bundle")
    parser.add_argument("--version-code", type=int)
    parser.add_argument("--bundle-revision", type=int)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    release_path = args.mobile / "release.json"
    current = json.loads(release_path.read_text(encoding="utf-8"))
    if args.version_code is not None:
        current["versionCode"] = args.version_code
    if args.bundle_revision is not None:
        current["bundleRevision"] = args.bundle_revision
    elif args.bundle or args.export:
        current["bundleRevision"] = int(current["bundleRevision"]) + 1
    if args.export:
        subprocess.run(["npx", "expo", "export", "--platform", "android", "--output-dir", "dist"], cwd=args.mobile, check=True)
        exported = next((args.mobile / "dist" / "_expo" / "static" / "js" / "android").glob("*.js"), None)
        if exported is None:
            exported = next((args.mobile / "dist").rglob("*.js"))
        args.bundle = exported
    args.dest.mkdir(parents=True, exist_ok=True)
    if args.apk:
        shutil.copyfile(args.apk, args.dest / "kili.apk")
    if args.bundle:
        shutil.copyfile(args.bundle, args.dest / "bundle.js")
        current["updateId"] = str(uuid.uuid4())
    published = {
        "native_version": current["nativeVersion"],
        "version_code": current["versionCode"],
        "bundle_revision": current["bundleRevision"],
        "runtime_version": current["nativeVersion"],
        "update_id": current.get("updateId") or "",
        "notes": args.notes,
    }
    (args.dest / "release.json").write_text(json.dumps(published, indent=2) + "\n", encoding="utf-8")
    release_path.write_text(json.dumps({
        "nativeVersion": current["nativeVersion"],
        "versionCode": current["versionCode"],
        "bundleRevision": current["bundleRevision"],
        "updateId": current.get("updateId") or "",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"published version_code={published['version_code']} bundle_revision={published['bundle_revision']} dest={args.dest}")


if __name__ == "__main__":
    main()
