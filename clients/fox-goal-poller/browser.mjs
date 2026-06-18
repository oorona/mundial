// browser.mjs — launch a browser context for the poller.
//
// Uses the real system Edge (with automation markers stripped) and loads the X session
// from auth.json (produced by import-cookies.mjs from your normal browser, or by
// login.mjs). We never automate the Google/X LOGIN flow — Google blocks that — we just
// reuse an already-authenticated session, so viewing the timeline works fine.

import { chromium } from "playwright";
import { existsSync } from "node:fs";

export async function launchContext(headless, { useStorage = true } = {}) {
  const launchOpts = {
    headless,
    args: ["--disable-blink-features=AutomationControlled"],
    ignoreDefaultArgs: ["--enable-automation"],
  };
  let browser;
  try {
    browser = await chromium.launch({ ...launchOpts, channel: "msedge" });
  } catch (e) {
    console.warn("[fgp] Edge unavailable, using bundled Chromium:", e.message);
    browser = await chromium.launch(launchOpts);
  }
  const ctxOpts = { viewport: headless ? { width: 1280, height: 1600 } : null };
  if (useStorage && existsSync("auth.json")) ctxOpts.storageState = "auth.json";
  return await browser.newContext(ctxOpts);
}
