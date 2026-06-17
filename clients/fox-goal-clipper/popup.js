// popup.js — renders the extension's decision log from chrome.storage.local 'log'.

function fmtTime(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function classFor(stage, ok) {
  if (stage === "error") return "err";
  if (stage === "upload" && ok) return "ok";
  if (stage === "classify" && ok) return "ok";
  return ok ? "ok" : "no";
}

async function render() {
  const { log = [] } = await chrome.storage.local.get("log");
  const list = document.getElementById("list");
  const empty = document.getElementById("empty");
  const counts = document.getElementById("counts");

  const uploaded = log.filter((e) => e.stage === "upload" && e.ok).length;
  const goals = log.filter((e) => e.stage === "classify" && e.ok).length;
  const errors = log.filter((e) => !e.ok && (e.stage === "error" || e.stage === "upload" || e.stage === "download" || e.stage === "classify")).length;
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
