// login.mjs — OPTIONAL alternative to import-cookies.mjs, for accounts that log into X
// directly (username/password, NOT "Sign in with Google" — Google blocks automated
// logins). Opens Edge, you log in, it saves the session to auth.json.
//
// If you use Google to sign into X, use  node import-cookies.mjs  instead.

import { launchContext } from "./browser.mjs";

const ctx = await launchContext(false, { useStorage: false }); // headed, fresh
const page = await ctx.newPage();
await page.goto("https://x.com/login");

console.log("\n  → Log into X in the browser window, then press ENTER here.\n");
await new Promise((resolve) => process.stdin.once("data", resolve));

await ctx.storageState({ path: "auth.json" });
console.log("Saved auth.json. You can now run:  npm start");
await ctx.browser().close();
process.exit(0);
