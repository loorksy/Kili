/** Reproducible calculation-only extraction; never modifies node_modules. */
import fs from 'node:fs';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
const root = fileURLToPath(new URL('../', import.meta.url));
const sourcePath = root + 'webui/node_modules/klinecharts/dist/index.esm.js';
const raw = fs.readFileSync(sourcePath, 'utf8');
const hash = crypto.createHash('sha256').update(raw).digest('hex');
const expected = fs.readFileSync(root + 'nanobot/charts/assets/upstream.sha256', 'utf8').trim();
if (hash !== expected) throw new Error('Pinned KLineChart calculation source changed; review before regenerating');
const start = raw.indexOf('function getSupportedIndicators()');
const end = raw.indexOf('\n/**', start);
if (start < 0 || end < 0) throw new Error('Calculation extraction boundary missing');
await build({ stdin: { contents: raw.slice(0, end) + '\nexport {getIndicatorClass};', sourcefile: 'klinecharts-9.8.12-calculation.js' },
  bundle: true, treeShaking: true, minify: true, platform: 'node', format: 'cjs', legalComments: 'none',
  outfile: root + 'nanobot/charts/assets/native-calculations.cjs',
  banner: { js: '/* KLineChart 9.8.12: Copyright (c) 2019 lihu, Apache-2.0. Calculation-only extract.\n * TypeScript helpers: Copyright Microsoft Corporation, ISC; see THIRD_PARTY_NOTICES.md. */' } });
