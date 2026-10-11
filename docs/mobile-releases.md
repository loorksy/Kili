# Publishing the Kili Android app

The installed app should not be replaced for an interface change. The gateway on the Kili domain serves both the APK and the update manifest.

Published files live in the data directory, next to `config.json`:

```text
/opt/kili/data/mobile-release/release.json
/opt/kili/data/mobile-release/kili.apk
/opt/kili/data/mobile-release/bundle.js
```

The WebUI download button uses `https://kili.lork.cloud/downloads/kili.apk`. That file is the arm64 debug build in `deploy/mobile-release/kili.apk`. Android will ask once to allow installation. The app reads `https://kili.lork.cloud/api/mobile/release` on launch. `/api/mobile/updates` serves the Hermes bundle in `deploy/mobile-release` when the server data directory does not already have one.

## Interface update

From a checkout that already has the mobile dependencies:

```sh
python scripts/publish_kili_mobile.py --dest /opt/kili/data/mobile-release --export --notes "Home layout"
sudo systemctl restart kili.service
```

`--export` runs `npx expo export --platform android` and bumps `bundleRevision`. On the next launch, a release build with Expo Updates reloads that bundle. The native version stays the same, so the owner is not asked to reinstall.

## Native update

Build the release APK, then publish it with a higher version code:

```sh
cd mobile
npx expo prebuild --platform android
cd android && ./gradlew assembleRelease
cd ../..
python scripts/publish_kili_mobile.py \
  --dest /opt/kili/data/mobile-release \
  --apk mobile/android/app/build/outputs/apk/release/app-release.apk \
  --version-code 2 \
  --notes "Native update"
sudo systemctl restart kili.service
```

The installed app compares `version_code`. When the published code is newer, it shows one button that opens the APK on this same host. Android then asks the owner to confirm the install. That confirmation is the only reinstall step, and it is only for a native change.

`mobile/app.json` points Expo Updates at `https://kili.lork.cloud/api/mobile/updates`. A different public origin needs that URL changed before `expo prebuild`. The launch check itself uses the gateway address stored on the phone, so the APK prompt follows the paired server.

Do not commit the APK or `mobile-release/` contents. They stay on the server, mode `0644` for the APK and `0644` for the manifest. The directory can be `0755`. No secret belongs in these files.
