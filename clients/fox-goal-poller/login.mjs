// login.mjs — log into X in a real Edge window and keep the session in profile/.
// Works if you can sign into X with a username/password. (If you use "Sign in with
// Google", Google blocks automated logins — use  node import-cookies.mjs  instead.)

import { chromium } from "playwright";

const ARGS = {
  args: ["--disable-blink-features=AutomationControlled"],
  ignoreDefaultArgs: ["--enable-automation"],
};

let ctx;
try {
  ctx = await chromium.launchPersistentContext("profile", { ...ARGS, headless: false, viewport: null, channel: "msedge" });
} catch (_) {
  ctx = await chromium.launchPersistentContext("profile", { ...ARGS, headless: false, viewport: null });
}
const page = ctx.pages()[0] || (await ctx.newPage());
await page.goto("https://x.com/login");

console.log("\n  → Log into X in the browser window, then press ENTER here.\n");
await new Promise((resolve) => process.stdin.once("data", resolve));

console.log("Login saved to profile/. You can now run:  npm start");
await ctx.close();
process.exit(0);
