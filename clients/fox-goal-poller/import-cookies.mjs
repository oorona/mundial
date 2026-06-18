// import-cookies.mjs — turn a Cookie-Editor export of your x.com cookies into auth.json.
//
// Why: you sign into X with "Sign in with Google", and Google blocks automated logins.
// So instead of logging in here, we reuse the session from your NORMAL browser:
//
//   1. In your everyday browser (where you're logged into X), install the "Cookie-Editor"
//      extension (Chrome/Edge Web Store).
//   2. Go to https://x.com (make sure you see your timeline).
//   3. Open Cookie-Editor → Export (choose "JSON") → it copies to your clipboard.
//   4. Paste into a new file named  cookies.json  in this folder, and save.
//   5. Run:  node import-cookies.mjs
//
// Then run  npm start.

import { readFileSync, writeFileSync, existsSync } from "node:fs";

if (!existsSync("cookies.json")) {
  console.error("Missing cookies.json — see the steps at the top of import-cookies.mjs.");
  process.exit(1);
}

const raw = JSON.parse(readFileSync("cookies.json", "utf8"));
const list = Array.isArray(raw) ? raw : raw.cookies || [];

function sameSite(s) {
  s = String(s || "").toLowerCase();
  if (s.includes("strict")) return "Strict";
  if (s.includes("lax")) return "Lax";
  if (s.includes("no_restriction") || s === "none") return "None";
  return "Lax";
}

const cookies = list
  .map((c) => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path || "/",
    expires:
      c.expirationDate != null
        ? Math.floor(Number(c.expirationDate))
        : c.expires && Number(c.expires) > 0
        ? Math.floor(Number(c.expires))
        : -1,
    httpOnly: !!c.httpOnly,
    secure: !!c.secure,
    sameSite: sameSite(c.sameSite),
  }))
  .filter((c) => c.name && c.value && c.domain);

if (!cookies.some((c) => c.name === "auth_token")) {
  console.warn("⚠  No 'auth_token' cookie found — make sure you exported x.com cookies while logged in.");
}

writeFileSync("auth.json", JSON.stringify({ cookies, origins: [] }, null, 2));
console.log(`Wrote auth.json with ${cookies.length} cookies. Now run:  npm start`);
