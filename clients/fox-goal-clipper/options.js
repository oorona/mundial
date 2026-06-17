// options.js — load/save config and request host permission for the server origin.

const FIELDS = ["serverUrl", "uploadKey", "llmApiKey", "llmModel", "handle", "threshold", "refreshSeconds", "reloadSeconds", "maxAgeMinutes"];

function $(id) {
  return document.getElementById(id);
}

function setStatus(msg, ok) {
  const el = $("status");
  el.textContent = msg;
  el.className = ok ? "ok" : "err";
}

// Load saved values.
chrome.storage.local.get(FIELDS, (cfg) => {
  for (const f of FIELDS) {
    if (cfg[f] != null) $(f).value = cfg[f];
  }
  if (!$("handle").value) $("handle").value = "FoxSoccer";
  if (!$("llmModel").value) $("llmModel").value = "gemini-flash-latest";
  if (!$("threshold").value) $("threshold").value = "0.6";
  if (!$("refreshSeconds").value) $("refreshSeconds").value = "90";
  if (!$("reloadSeconds").value) $("reloadSeconds").value = "300";
  if (!$("maxAgeMinutes").value) $("maxAgeMinutes").value = "15";
});

$("save").addEventListener("click", async () => {
  const cfg = {};
  for (const f of FIELDS) cfg[f] = $(f).value.trim();

  if (!cfg.serverUrl || !cfg.uploadKey || !cfg.llmApiKey) {
    setStatus("Server URL, upload key, and Gemini key are required.", false);
    return;
  }

  // Request permission to POST to the configured server origin (optional_host_permissions).
  let origin;
  try {
    origin = new URL(cfg.serverUrl).origin + "/*";
  } catch (_) {
    setStatus("Server URL is not a valid URL.", false);
    return;
  }

  chrome.permissions.request({ origins: [origin] }, (granted) => {
    if (!granted) {
      setStatus("Permission for the server origin was denied — uploads will fail.", false);
      return;
    }
    chrome.storage.local.set(cfg, () => setStatus("Saved.", true));
  });
});
