// validate.mjs — headless validator for the extension's non-DOM logic.
//
// Exercises the SAME clip-core.js the extension runs, against the real X syndication
// API, so you can confirm the brittle external bits work without loading Chrome. The DOM
// detection in content.js genuinely needs a browser — see the manual checklist in
// README.md for that part.
//
//   node validate.mjs                         # static + syndication reachability
//   node validate.mjs <fox_video_tweet_url>   # + real clip download
//
// Requires Node 18+ (global fetch/FormData/Blob).

import { readFileSync, existsSync } from "node:fs";
import {
  synToken, parseTweetId, fetchSyndication, downloadBestClip,
} from "./clip-core.js";

let fails = 0;
const ok = (m) => console.log("  \x1b[32m✓\x1b[0m " + m);
const bad = (m) => { console.log("  \x1b[31m✗\x1b[0m " + m); fails++; };
const skip = (m) => console.log("  – " + m);

const here = (p) => new URL("./" + p, import.meta.url);

console.log("Validating fox-goal-clipper\n" + "=".repeat(40));

// 1. Manifest + referenced files
console.log("\n[static]");
try {
  const mf = JSON.parse(readFileSync(here("manifest.json")));
  mf.manifest_version === 3 ? ok("manifest_version 3") : bad("manifest_version must be 3");
  const files = [
    mf.background?.service_worker,
    ...(mf.content_scripts || []).flatMap((c) => c.js || []),
    mf.options_page,
    mf.action?.default_popup,
  ].filter(Boolean);
  for (const f of files) existsSync(here(f)) ? ok(`file present: ${f}`) : bad(`missing file: ${f}`);
  mf.background?.type === "module" ? ok("service worker is type:module") : bad("background.type should be 'module'");
} catch (e) { bad("manifest: " + e.message); }

// 2. Token format
/^[a-z0-9]+$/.test(synToken("1790000000000000000"))
  ? ok("synToken produces a clean token")
  : bad("synToken format");

// 3. Syndication endpoint reachable (sample tweet id 20 = @jack's first tweet)
console.log("\n[live: X syndication]");
try {
  const j = await fetchSyndication("20");
  j && typeof j === "object" && "text" in j
    ? ok(`syndication reachable — sample text: "${String(j.text).slice(0, 40)}"`)
    : bad("syndication returned an unexpected shape");
} catch (e) { bad("syndication unreachable: " + e.message + " (X may have changed the endpoint)"); }

// 4. Optional: real clip download
const tweetArg = process.argv[2];
if (tweetArg) {
  const id = parseTweetId(tweetArg);
  if (!id) bad("could not parse a tweet id from: " + tweetArg);
  else {
    try {
      const r = await downloadBestClip(id);
      if (r.variants && r.blob) ok(`download: ${r.variants} mp4 variant(s), got ${(r.bytes / 1048576).toFixed(2)} MB`);
      else bad("no mp4 variant for that tweet (HLS-only, or not a video tweet)");
    } catch (e) { bad("download failed: " + e.message); }
  }
} else skip("clip download (pass a Fox video tweet URL to test)");

console.log("\n" + "=".repeat(40));
console.log(fails ? `\x1b[31mFAILED — ${fails} check(s)\x1b[0m` : "\x1b[32mALL CHECKS PASSED\x1b[0m");
process.exit(fails ? 1 : 0);
