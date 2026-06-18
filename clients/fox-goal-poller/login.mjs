// login.mjs — one-time: open a real (Edge) browser, log into X, keep the session in
// the local ./profile dir. The headless poller then reuses it, so it stays signed in.

import { launchContext } from "./browser.mjs";

const ctx = await launchContext(false); // headed
const page = ctx.pages()[0] || (await ctx.newPage());
await page.goto("https://x.com/login");

console.log("\n  → Log into X (Twitter) in the browser window that just opened.");
console.log("  → Once you can see your timeline, come back here and press ENTER.\n");

await new Promise((resolve) => process.stdin.once("data", resolve));

console.log("Login saved to the local profile. You can now run:  npm start");
await ctx.close();
process.exit(0);
