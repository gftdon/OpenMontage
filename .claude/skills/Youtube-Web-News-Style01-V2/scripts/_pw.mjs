// Resolve the `playwright` package from the usual local install spots so the
// capture scripts run from inside .claude/skills (which has no node_modules).
import { existsSync } from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';
export async function loadPlaywright() {
  try { return await import('playwright'); } catch {}
  const cands = [path.join(os.homedir(), 'node_modules/playwright/index.mjs')];
  try { cands.push(path.join(execSync('npm root -g').toString().trim(), 'playwright/index.mjs')); } catch {}
  for (const c of cands) if (existsSync(c)) return await import(c);
  throw new Error('playwright not found. Install once: `cd ~ && npm i playwright@latest && npx playwright install chromium`');
}
