/** Launch check against the gateway manifest. The server owns the published numbers. */

export interface PublishedRelease {
  version_code?: unknown;
  bundle_revision?: unknown;
  apk_url?: unknown;
  apk_available?: unknown;
  bundle_url?: unknown;
}

export function updateAction(
  versionCode: number,
  bundleRevision: number,
  remote: PublishedRelease,
): "apk" | "bundle" | null {
  if (typeof remote.version_code !== "number" || typeof remote.bundle_revision !== "number") return null;
  if (remote.version_code > versionCode) return "apk";
  if (remote.version_code === versionCode && remote.bundle_revision > bundleRevision) return "bundle";
  return null;
}

export async function applyBundleUpdate(): Promise<boolean> {
  try {
    const Updates = await import("expo-updates");
    if (!Updates.isEnabled) return false;
    const check = await Updates.checkForUpdateAsync();
    if (!check.isAvailable) return false;
    await Updates.fetchUpdateAsync();
    await Updates.reloadAsync();
    return true;
  } catch {
    return false;
  }
}

export function apkUrl(baseUrl: string, remote: PublishedRelease): string | null {
  if (remote.apk_available !== true || typeof remote.apk_url !== "string") return null;
  return new URL(remote.apk_url, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`).toString();
}
