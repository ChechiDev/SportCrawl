/**
 * popup.js — fbrefly extension popup
 *
 * Reads work_server_url and work_server_token from chrome.storage.sync on load.
 * Writes both values on Save click.
 * Displays last known connection status from chrome.storage.local.
 */

const DEFAULT_WORK_SERVER_URL = "http://localhost:9731";

const urlInput = document.getElementById("work_server_url");
const tokenInput = document.getElementById("work_server_token");
const saveBtn = document.getElementById("save");
const statusEl = document.getElementById("status");

// Populate fields from storage on open.
chrome.storage.sync.get(
  { work_server_url: DEFAULT_WORK_SERVER_URL, work_server_token: "" },
  (syncData) => {
    urlInput.value = syncData.work_server_url;
    tokenInput.value = syncData.work_server_token;
  }
);

// Show last known connection status from local storage.
chrome.storage.local.get({ last_status: null, last_status_at: null }, (localData) => {
  if (localData.last_status !== null) {
    const ts = localData.last_status_at
      ? new Date(localData.last_status_at).toLocaleTimeString()
      : "";
    const isOk = localData.last_status === "ok";
    statusEl.textContent = `Last connection: ${localData.last_status}${ts ? " at " + ts : ""}`;
    statusEl.className = isOk ? "ok" : "err";
  }
});

// Save configuration on button click.
saveBtn.addEventListener("click", () => {
  const work_server_url = urlInput.value.trim() || DEFAULT_WORK_SERVER_URL;
  const work_server_token = tokenInput.value.trim();

  chrome.storage.sync.set({ work_server_url, work_server_token }, () => {
    if (chrome.runtime.lastError) {
      statusEl.textContent = "Save failed: " + chrome.runtime.lastError.message;
      statusEl.className = "err";
      return;
    }
    statusEl.textContent = "Saved.";
    statusEl.className = "ok";
    setTimeout(() => {
      if (statusEl.textContent === "Saved.") {
        statusEl.textContent = "";
      }
    }, 2000);
  });
});
