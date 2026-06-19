// browser.mjs — launch the browser context for the poller, using whichever X session
// you have. Two supported sources (it auto-detects):
//   • profile/   — a persistent Edge login created by login.mjs (works if you can log
//                  into X with a username/password)
//   • auth.json  — cookies imported from your normal browser by import-cookies.mjs
//                  (use this if you sign into X with "Sign in with Google")
// Real Edge + automation markers stripped, so X is happy either way.
//
// Memory: the poller only reads the timeline DOM (tweet ids + text) and downloads clips
// via the syndication API — it NEVER plays video in the browser. So we block image/media/
// font requests, which keeps headless Chromium's RAM/CPU flat. Without this, scrolling a
// video-heavy timeline (e.g. @FOXSports) makes Chromium load dozens of video players and
// balloon memory until a low-RAM VM thrashes and freezes.

import { chromium } from "playwright";
import { existsSync } from "node:fs";

const ARGS = {
  args: [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage", // don't use the tiny /dev/shm — avoids OOM crashes on small VMs
    "--disable-gpu",
    "--mute-audio",
    "--disable-background-networking",
    "--disable-features=Translate,BackForwardCache,MediaRouter",
    "--disk-cache-size=10000000", // cap Chromium's on-disk cache (~10MB) — the page is a
                                  // long-running tab; an uncapped media cache is heavy disk I/O
    "--media-cache-size=1",
    "--autoplay-policy=document-user-activation-required", // never autoplay timeline videos
  ],
  ignoreDefaultArgs: ["--enable-automation"],
};

// Abort the heavy resource types — the page never needs them for scraping.
async function blockHeavy(context) {
  try {
    await context.route("**/*", (route) => {
      const t = route.request().resourceType();
      if (t === "image" || t === "media" || t === "font") return route.abort();
      return route.continue();
    });
  } catch (_) {}
}

export async function launchContext(headless) {
  const viewport = headless ? { width: 1100, height: 1400 } : null;

  // 1) Persistent Edge login profile (from login.mjs), if present.
  if (existsSync("profile")) {
    const opts = { ...ARGS, headless, viewport };
    let ctx;
    try {
      ctx = await chromium.launchPersistentContext("profile", { ...opts, channel: "msedge" });
    } catch (_) {
      ctx = await chromium.launchPersistentContext("profile", opts);
    }
    await blockHeavy(ctx);
    // launchPersistentContext owns its browser — close() tears the whole thing down.
    return { context: ctx, close: () => ctx.close().catch(() => {}) };
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
  const ctx = await browser.newContext(ctxOpts);
  await blockHeavy(ctx);
  return {
    context: ctx,
    close: async () => {
      await ctx.close().catch(() => {});
      await browser.close().catch(() => {});
    },
  };
}
