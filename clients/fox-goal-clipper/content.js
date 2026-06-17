// content.js — runs on x.com / twitter.com.
//
// Watches the timeline for newly-rendered posts that (a) are authored by the
// configured handle and (b) contain a video, then forwards the tweet id + handle +
// text to the background service worker. The background worker does the LLM goal
// check, clip download, and upload — the content script only DETECTS candidates.
//
// NOTE: this depends on x.com's DOM structure (data-testid attributes, the
// /handle/status/id permalink shape). X changes its frontend often; if detection
// stops working, these selectors are the first thing to update.

(() => {
  const SEEN = new Set();            // in-tab dedup (the background worker dedups durably too)
  let monitoredHandle = "";

  chrome.storage.local.get(["handle"], (cfg) => {
    monitoredHandle = normHandle(cfg.handle);
  });
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.handle) monitoredHandle = normHandle(changes.handle.newValue);
  });

  function normHandle(h) {
    return String(h || "").trim().replace(/^@/, "").toLowerCase();
  }

  function scan() {
    const articles = document.querySelectorAll("article");
    for (const art of articles) {
      if (art.dataset.fgcSeen) continue;

      // The tweet's own permalink is the one wrapping the timestamp; fall back to
      // the first /status/ link. Shape: /<handle>/status/<id>.
      const link =
        art.querySelector('a[href*="/status/"]:has(time)') ||
        art.querySelector('a[href*="/status/"]');
      const m = link && link.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
      if (!m) continue;

      const handle = m[1].toLowerCase();
      const tweetId = m[2];

      // Only the monitored account (skip retweets/quotes from others).
      if (monitoredHandle && handle !== monitoredHandle) continue;

      // Must contain a native video.
      const hasVideo = art.querySelector(
        '[data-testid="videoComponent"], [data-testid="videoPlayer"], video'
      );
      if (!hasVideo) continue;

      art.dataset.fgcSeen = "1";
      if (SEEN.has(tweetId)) continue;
      SEEN.add(tweetId);

      const textEl = art.querySelector('[data-testid="tweetText"]');
      const text = textEl ? textEl.innerText : "";

      chrome.runtime.sendMessage({ type: "fgc_candidate", tweetId, handle, text });
    }
  }

  // Initial sweep + observe the timeline for infinite-scroll additions.
  const debounced = (() => {
    let t = null;
    return () => {
      clearTimeout(t);
      t = setTimeout(scan, 400);
    };
  })();

  const obs = new MutationObserver(debounced);
  obs.observe(document.documentElement, { childList: true, subtree: true });
  debounced();
})();
