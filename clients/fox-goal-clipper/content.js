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
  let cfg = { handle: "", refreshSeconds: 90, reloadSeconds: 300, maxAgeMinutes: 15 };
  let timersStarted = false;
  let observer = null;

  // After the extension is reloaded/updated, an already-open tab keeps running this
  // (now orphaned) script; chrome.* calls then throw "Extension context invalidated".
  // Detect that, stop cleanly, and never spew errors — a tab reload injects a fresh one.
  function alive() {
    return !!(chrome.runtime && chrome.runtime.id);
  }
  function stop() {
    try { observer && observer.disconnect(); } catch (_) {}
  }
  function send(msg) {
    if (!alive()) return stop();
    try {
      chrome.runtime.sendMessage(msg);
    } catch (_) {
      stop();
    }
  }

  function applyCfg(c) {
    cfg.handle = String(c.handle || "").trim().replace(/^@/, "").toLowerCase();
    const r = Number(c.refreshSeconds);
    const rl = Number(c.reloadSeconds);
    const ma = Number(c.maxAgeMinutes);
    if (!Number.isNaN(r)) cfg.refreshSeconds = r;
    if (!Number.isNaN(rl)) cfg.reloadSeconds = rl;
    if (!Number.isNaN(ma)) cfg.maxAgeMinutes = ma;
  }

  function scan() {
    if (!alive()) return stop();
    let found = 0;
    for (const art of document.querySelectorAll("article")) {
      if (art.dataset.fgcSeen) continue;
      // The tweet's own permalink wraps the timestamp; find the status link that
      // contains a <time>, else the first one. (No :has() — older Chrome throws on it.)
      let link = null;
      for (const a of art.querySelectorAll('a[href*="/status/"]')) {
        if (a.querySelector("time")) { link = a; break; }
      }
      if (!link) link = art.querySelector('a[href*="/status/"]');
      const m = link && link.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
      if (!m) continue;
      const handle = m[1].toLowerCase();
      const tweetId = m[2];
      if (cfg.handle && handle !== cfg.handle) continue;
      const hasVideo = art.querySelector(
        '[data-testid="videoComponent"], [data-testid="videoPlayer"], video'
      );
      if (!hasVideo) continue;
      // Age gate: skip posts older than maxAgeMinutes so we never classify the backlog
      // of old videos on load/reload, and never upload a stale goal that could mis-pair
      // with a current live match. Posts with no timestamp fall through (processed once).
      const timeEl = art.querySelector("time[datetime]");
      const posted = timeEl ? Date.parse(timeEl.getAttribute("datetime")) : NaN;
      if (!Number.isNaN(posted) && Date.now() - posted > cfg.maxAgeMinutes * 60000) {
        art.dataset.fgcSeen = "1";
        continue;
      }
      art.dataset.fgcSeen = "1";
      if (SEEN.has(tweetId)) continue;
      SEEN.add(tweetId);
      found++;
      const textEl = art.querySelector('[data-testid="tweetText"]');
      const text = textEl ? textEl.innerText : "";
      send({ type: "fgc_candidate", tweetId, handle, text });
    }
    if (found) send({ type: "fgc_scan", found });
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

  // Heartbeat: report "I'm alive and watching" + how many video posts (and how many
  // from the monitored handle) are on the page right now. Drives the popup status line
  // so it's always obvious the extension is running — even when there are no goals.
  function heartbeat() {
    if (!alive()) return stop();
    let videos = 0, mine = 0;
    for (const art of document.querySelectorAll("article")) {
      if (!art.querySelector('[data-testid="videoComponent"], [data-testid="videoPlayer"], video')) continue;
      videos++;
      const l = art.querySelector('a[href*="/status/"]');
      const mm = l && l.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
      if (mm && (!cfg.handle || mm[1].toLowerCase() === cfg.handle)) mine++;
    }
    send({ type: "fgc_heartbeat", handle: cfg.handle, url: location.pathname, videos, mine });
  }

  function startTimers() {
    if (timersStarted) return;
    timersStarted = true;
    heartbeat();
    setInterval(heartbeat, 30000);
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
  observer = new MutationObserver(debounced);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  debounced();

  chrome.storage.local.get(["handle", "refreshSeconds", "reloadSeconds", "maxAgeMinutes"], (c) => {
    applyCfg(c);
    startTimers();
  });
  chrome.storage.onChanged.addListener((changes) => {
    const c = {};
    for (const k in changes) c[k] = changes[k].newValue;
    applyCfg(c);
  });
})();
