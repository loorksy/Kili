"""The phone update check installs an APK only when the native build changed."""
import json
import subprocess
import sys
from pathlib import Path

from nanobot.webui.mobile_release import asset_hash, expo_update_body, read_release, update_action


def test_publish_script_copies_the_bundle_and_bumps_the_revision(tmp_path):
    mobile = tmp_path / "mobile"
    mobile.mkdir()
    (mobile / "release.json").write_text(json.dumps({
        "nativeVersion": "0.1.0", "versionCode": 1, "bundleRevision": 1, "updateId": "",
    }), encoding="utf-8")
    bundle = tmp_path / "app.js"
    bundle.write_text("console.log('kili')\n", encoding="utf-8")
    dest = tmp_path / "mobile-release"
    root = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, str(root / "scripts/publish_kili_mobile.py"), "--dest", str(dest), "--mobile", str(mobile), "--bundle", str(bundle), "--notes", "Home"], check=True)
    published = json.loads((dest / "release.json").read_text(encoding="utf-8"))
    assert published["bundle_revision"] == 2
    assert (dest / "bundle.js").read_text(encoding="utf-8").startswith("console.log")
    assert published["update_id"]


def test_native_bump_asks_for_an_apk_and_a_bundle_stays_on_the_same_apk():
    remote = {"version_code": 2, "bundle_revision": 4}
    assert update_action(1, 9, remote) == "apk"
    assert update_action(2, 3, {"version_code": 2, "bundle_revision": 4}) == "bundle"
    assert update_action(2, 4, {"version_code": 2, "bundle_revision": 4}) is None


def test_release_files_and_expo_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.webui.mobile_release.get_config_path", lambda: tmp_path / "config.json")
    directory = tmp_path / "mobile-release"
    directory.mkdir()
    bundle = b"console.log('kili')"
    (directory / "bundle.js").write_bytes(bundle)
    (directory / "kili.apk").write_bytes(b"apk")
    (directory / "release.json").write_text(json.dumps({
        "native_version": "0.2.0", "version_code": 2, "bundle_revision": 5,
        "runtime_version": "0.2.0", "update_id": "8c2d6b5a-1d2e-4f3a-9b8c-7d6e5f4a3b2c", "notes": "Home",
    }), encoding="utf-8")
    release = read_release(directory)
    assert release["apk_available"] is True
    assert release["bundle_revision"] == 5
    status, _body, _content = expo_update_body(release, bundle, "https://kili.lork.cloud/api/mobile/bundle", release["update_id"])
    assert status == 204
    status, body, content_type = expo_update_body(release, bundle, "https://kili.lork.cloud/api/mobile/bundle", None)
    assert status == 200 and "multipart/mixed" in content_type
    assert asset_hash(bundle) in body.decode()
