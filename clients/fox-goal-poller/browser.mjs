// browser.mjs — launch a persistent browser context that X won't flag as automated.
//
// Two tricks defeat the "this browser may not be secure" login block:
//   1. use a REAL browser (system Edge — always present on Windows) instead of the
//      bundled test Chromium;
//   2. strip the automation markers (--enable-automation / navigator.webdriver).
// The login is kept in a persistent ./profile dir, so the headless poller stays signed in.

import { chromium } from "playwright";

const PROFILE = "profile";

export async function launchContext(headless) {
  const opts = {
    headless,
    args: ["--disable-blink-features=AutomationControlled"],
    ignoreDefaultArgs: ["--enable-automation"],
    viewport: headless ? { width: 1280, height: 1600 } : null,
  };
  // Prefer system Edge (real browser, pre-installed on Windows); fall back to Chromium.
  try {
    return await chromium.launchPersistentContext(PROFILE, { ...opts, channel: "msedge" });
  } catch (e) {
    console.warn("[fgp] Edge unavailable, using bundled Chromium:", e.message);
    return await chromium.launchPersistentContext(PROFILE, opts);
  }
}
