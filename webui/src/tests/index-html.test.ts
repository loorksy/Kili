import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("index.html", () => {
  it("keeps browser zoom available", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    expect(viewport).toContain("width=device-width");
    expect(viewport).not.toContain("user-scalable=no");
    expect(viewport).not.toMatch(/maximum-scale\s*=\s*1(?:\.0)?(?:,|$)/);
  });

  it("lets iOS keep standalone content inside the safe area", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    expect(viewport).toContain("viewport-fit=auto");
    expect(viewport).not.toContain("viewport-fit=cover");
  });

  it("provides light and dark PWA chrome colors", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "public/manifest.json"), "utf8"),
    ) as {
      background_color?: string;
      theme_color?: string;
      color_scheme_dark?: { background_color?: string; theme_color?: string };
    };
    const document = new DOMParser().parseFromString(html, "text/html");
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    const lightBodyBackground = html.match(/body\s*{[^}]*background:\s*([^;]+);/s)?.[1]?.trim();
    const darkBodyBackground = html.match(
      /html\.dark body\s*{[^}]*background:\s*([^;]+);/s,
    )?.[1]?.trim();

    expect(themeColor?.content).toBe("#ffffff");
    expect(themeColor?.dataset.themeColorLight).toBe("#ffffff");
    expect(themeColor?.dataset.themeColorDark).toBe("#303030");
    expect(lightBodyBackground).toBe("#ffffff");
    expect(darkBodyBackground).toBe("#303030");
    expect(manifest.background_color).toBe("#ffffff");
    expect(manifest.theme_color).toBe("#ffffff");
    expect(manifest.color_scheme_dark?.background_color).toBe("#303030");
    expect(manifest.color_scheme_dark?.theme_color).toBe("#303030");
  });

  it("names the installed app Kili", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "public/manifest.json"), "utf8"),
    ) as { name?: string; short_name?: string; description?: string; icons?: { src: string }[] };

    expect(html).toContain('content="Kili web UI — chat with your Kili workspace."');
    expect(html).toContain('name="apple-mobile-web-app-title" content="Kili"');
    expect(html).toContain('href="/brand/kili_mark.svg"');
    expect(html).toContain('title: "كيلي"');
    expect(manifest.name).toBe("Kili");
    expect(manifest.short_name).toBe("Kili");
    expect(manifest.description).toBe("Kili (كيلي)");
    expect(manifest.icons?.map((icon) => icon.src)).toEqual([
      "/brand/kili_apple_touch.png",
      "/brand/kili_icon_192.png",
      "/brand/kili_icon_512.png",
      "/brand/kili_icon_maskable.png",
    ]);
  });
});
