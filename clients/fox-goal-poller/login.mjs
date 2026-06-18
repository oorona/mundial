// login.mjs — one-time: open a real browser, log into X, save the session to auth.json.
// The headless poller then reuses that session, so it never has to log in again.

import { chromium } from "playwright";

const b = await chromium.launch({ headless: false });
const ctx = await b.newContext();
const page = await ctx.newPage();
await page.goto("https://x.com/login");

console.log("\n  → Log into X (Twitter) in the browser window that just opened.");
console.log("  → Once you can see your timeline, come back here and press ENTER.\n");

await new Promise((resolve) => process.stdin.once("data", resolve));

await ctx.storageState({ path: "auth.json" });
console.log("Saved session to auth.json. You can now run:  npm start");
await b.close();
process.exit(0);
