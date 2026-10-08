import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
for (const extension of ["js", "css"]) {
  const file = `../nanobot/charts/assets/chart-renderer.${extension}`;
  writeFileSync(`${file}.sha256`, createHash("sha256").update(readFileSync(file)).digest("hex") + "\n");
}
