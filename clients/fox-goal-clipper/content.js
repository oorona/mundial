// content.js — runs on x.com / twitter.com.
//
// Two jobs:
//  1. DETECT: a MutationObserver watches the DOM; when a new <article> with a video
//     authored by the monitored handle appears, forward {tweetId, handle, text} to the
//     background worker (which classifies, downloads, uploads).
//  2. KEEP FRESH: X holds new profile posts behind a "Show N posts" pill — they do NOT
//     enter the DOM on their own — so we click that pill on an interval and hard-reload
//     on a longer interval as a backstop. Without this the watcher never sees new goals.
//
// Selectors depend on x.com's DOM (data-testid, the /handle/status/id permalink). X
// changes its frontend often; if detection breaks, update the selectors here first.

(() => {
  const SEEN = new Set(); // in-tab dedup (the background worker dedups durably too)
  let cfg = { handle: "", refreshSeconds: 90, reloadSeconds: 300 };
  let timersStarted = false;

  function applyCfg(c) {
    cfg.handle = String(c.handle || "").trim().replace(/^@/, "").toLowerCase();
    const r = Number(c.refreshSeconds);
    const rl = Number(c.reloadSeconds);
    if (!Number.isNaN(r)) cfg.refreshSeconds = r;
    if (!Number.isNaN(rl)) cfg.reloadSeconds = rl;
  }

  function scan() {
    let found = 0;
    for (const art of document.querySelectorAll("article")) {
      if (art.dataset.fgcSeen) continue;
      const link =
        art.querySelector('a[href*="/status/"]:has(time)') ||
        art.querySelector('a[href*="/status/"]');
      const m = link && link.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
      if (!m) continue;
      const handle = m[1].toLowerCase();
      const tweetId = m[2];
      if (cfg.handle && handle !== cfg.handle) continue;
      const hasVideo = art.querySelector(
        '[data-testid="videoComponent"], [data-testid="videoPlayer"], video'
      );
      if (!hasVideo) continue;
      art.dataset.fgcSeen = "1";
      if (SEEN.has(tweetId)) continue;
      SEEN.add(tweetId);
      found++;
      const textEl = art.querySelector('[data-testid="tweetText"]');
      const text = textEl ? textEl.innerText : "";
      chrome.runtime.sendMessage({ type: "fgc_candidate", tweetId, handle, text });
    }
    if (found) chrome.runtime.sendMessage({ type: "fgc_scan", found });
  }

  // X buffers new profile posts behind a button like "Show 3 posts" — click it to pull
  // them into the DOM (keeps scroll position). Returns true if one was clicked.
  function clickNewPostsPill() {
    for (const el of document.querySelectorAll('[role="button"], a[role="link"], div[role="button"], span')) {
      const t = (el.textContent || "").trim().toLowerCase();
      if (/^show\s+\d+\s+post/.test(t) || /\bsee\s+new\s+posts?\b/.test(t)) {
        el.click();
        return true;
      }
    }
    return false;
  }

  function startTimers() {
    if (timersStarted) return;
    timersStarted = true;
    if (cfg.refreshSeconds > 0) {
      setInterval(() => clickNewPostsPill(), Math.max(15, cfg.refreshSeconds) * 1000);
    }
    if (cfg.reloadSeconds > 0) {
      setInterval(() => location.reload(), Math.max(60, cfg.reloadSeconds) * 1000);
    }
  }

  // Start detecting immediately; load config then start the refresh timers.
  const debounced = (() => {
    let t = null;
    return () => {
      clearTimeout(t);
      t = setTimeout(scan, 400);
    };
  })();
  new MutationObserver(debounced).observe(document.documentElement, { childList: true, subtree: true });
  debounced();

  chrome.storage.local.get(["handle", "refreshSeconds", "reloadSeconds"], (c) => {
    applyCfg(c);
    startTimers();
  });
  chrome.storage.onChanged.addListener((changes) => {
    const c = {};
    for (const k in changes) c[k] = changes[k].newValue;
    applyCfg(c);
  });
})();
