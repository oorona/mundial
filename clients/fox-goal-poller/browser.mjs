// browser.mjs — launch the browser context for the poller, using whichever X session
// you have. Two supported sources (it auto-detects):
//   • profile/   — a persistent Edge login created by login.mjs (works if you can log
//                  into X with a username/password)
//   • auth.json  — cookies imported from your normal browser by import-cookies.mjs
//                  (use this if you sign into X with "Sign in with Google")
// Real Edge + automation markers stripped, so X is happy either way.

import { chromium } from "playwright";
import { existsSync } from "node:fs";

const ARGS = {
  args: ["--disable-blink-features=AutomationControlled"],
  ignoreDefaultArgs: ["--enable-automation"],
};

export async function launchContext(headless) {
  const viewport = headless ? { width: 1280, height: 1600 } : null;

  // 1) Persistent Edge login profile (from login.mjs), if present.
  if (existsSync("profile")) {
    const opts = { ...ARGS, headless, viewport };
    try {
      return await chromium.launchPersistentContext("profile", { ...opts, channel: "msedge" });
    } catch (_) {
      return await chromium.launchPersistentContext("profile", opts);
    }
  }

  // 2) Otherwise a regular context + cookies from auth.json (import-cookies.mjs).
  let browser;
  try {
    browser = await chromium.launch({ ...ARGS, headless, channel: "msedge" });
  } catch (e) {
    console.warn("[fgp] Edge unavailable, using bundled Chromium:", e.message);
    browser = await chromium.launch({ ...ARGS, headless });
  }
  const ctxOpts = { viewport };
  if (existsSync("auth.json")) ctxOpts.storageState = "auth.json";
  return await browser.newContext(ctxOpts);
}
