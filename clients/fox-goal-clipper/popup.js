// popup.js — renders the extension's decision log from chrome.storage.local 'log'.

function fmtTime(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function classFor(stage, ok) {
  if (stage === "error") return "err";
  if (stage === "GOAL") return "ok";
  if (stage === "upload" && ok) return "ok";
  return ok ? "ok" : "no";
}

function renderStatus(status) {
  const el = document.getElementById("status");
  if (!status || !status.ts) {
    el.innerHTML = '<span style="color:#b45309;">○ no heartbeat yet — open the Fox profile on x.com and reload that tab</span>';
    return;
  }
  const age = Math.round((Date.now() - status.ts) / 1000);
  const live = age < 90;
  const dot = live ? '<span style="color:#16a34a;">●</span>' : '<span style="color:#b45309;">●</span>';
  const ago = age < 60 ? `${age}s ago` : `${Math.round(age / 60)}m ago`;
  el.innerHTML =
    `${dot} Watching <b>@${status.handle || "?"}</b> on <code>${status.url || "?"}</code><br>` +
    `${status.mine ?? 0} matching video post(s) on page (${status.videos ?? 0} total) · last check ${ago}`;
}

async function render() {
  const store = await chrome.storage.local.get(["log", "status"]);
  const log = store.log || [];
  renderStatus(store.status);
  const list = document.getElementById("list");
  const empty = document.getElementById("empty");
  const counts = document.getElementById("counts");

  const uploaded = log.filter((e) => e.stage === "upload" && e.ok).length;
  const goals = log.filter((e) => e.stage === "GOAL").length;
  const errors = log.filter((e) => !e.ok && (e.stage === "error" || e.stage === "upload" || e.stage === "download")).length;
  counts.innerHTML =
    `<b>${uploaded}</b> uploaded · <b>${goals}</b> goals detected · <b>${errors}</b> issues · ${log.length} entries`;

  empty.style.display = log.length ? "none" : "block";
  list.innerHTML = log
    .map((e) => {
      const cls = classFor(e.stage, e.ok);
      const tid = e.tweetId ? `<span class="tid">#${e.tweetId.slice(-6)}</span> ` : "";
      return `<div class="row"><span class="ts">${fmtTime(e.ts)}</span> ` +
why(cls, e.stage) + ` ${tid}${escapeHtml(e.detail)}</div>`;
    })
    .join("");
}

function why(cls, stage) {
  return `<span class="stage ${cls}">${stage}</span>`;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

document.getElementById("clear").addEventListener("click", async () => {
  await chrome.storage.local.set({ log: [] });
  render();
});
document.getElementById("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

render();
setInterval(render, 2000); // live-update while the popup is open
