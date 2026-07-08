/**
 * background.js — fbrefly MV3 service worker
 *
 * Responsibilities:
 *   1. CF clearance capture: listen for cf_clearance cookie on fbref.com, POST to work_server.
 *   2. Task poll loop: chrome.alarms fires every 1 min, GET /api/tasks/next, execute, POST result.
 *   3. Auth: every outbound request carries Authorization: Bearer {token}.
 *   4. Backoff: exponential on 5xx / network errors (base 2s, x2, cap 60s); reset on success.
 *   5. Fatal stop: 401/403 → log error, stop polling (bad token, manual fix required).
 */

const ALARM_NAME = "fetchTaskPoll";
const ALARM_PERIOD_MINUTES = 1;
const BACKOFF_BASE_MS = 2000;
const BACKOFF_CAP_MS = 60000;

let _config = { work_server_url: "", work_server_token: "" };
let _backoffMs = BACKOFF_BASE_MS;
let _fatalStop = false;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

/**
 * Load config from chrome.storage.sync. Returns true when both url and token
 * are present; false otherwise.
 */
async function loadConfig() {
  const { fatalStop } = await chrome.storage.local.get("fatalStop");
  _fatalStop = !!fatalStop;

  return new Promise((resolve) => {
    chrome.storage.sync.get(
      { work_server_url: "", work_server_token: "" },
      (data) => {
        _config = {
          work_server_url: data.work_server_url.trim(),
          work_server_token: data.work_server_token.trim(),
        };
        resolve(_config.work_server_url !== "" && _config.work_server_token !== "");
      }
    );
  });
}

// ---------------------------------------------------------------------------
// Fatal stop — persisted across service worker restarts
// ---------------------------------------------------------------------------

async function setFatalStop() {
  _fatalStop = true;
  await chrome.storage.local.set({ fatalStop: true });
  persistStatus("fatal");
}

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

function authHeaders() {
  return { Authorization: `Bearer ${_config.work_server_token}` };
}

// ---------------------------------------------------------------------------
// Status persistence (last connection status shown in popup)
// ---------------------------------------------------------------------------

function persistStatus(status) {
  chrome.storage.local.set({ last_status: status, last_status_at: Date.now() });
}

// ---------------------------------------------------------------------------
// CF clearance capture
// ---------------------------------------------------------------------------

chrome.cookies.onChanged.addListener((details) => {
  const cookie = details.cookie;
  // removed covers all removal causes; explicit set fires with removed=false
  const isSet = !details.removed;

  if (
    cookie.name !== "cf_clearance" ||
    !cookie.domain.includes("fbref.com") ||
    !isSet
  ) {
    return;
  }

  if (!_config.work_server_url || !_config.work_server_token) {
    console.warn("[fbrefly] cf_clearance captured but work_server not configured — skipping POST.");
    return;
  }

  const url = `${_config.work_server_url}/api/clearance`;
  fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      cf_clearance: cookie.value,
      domain: cookie.domain,
    }),
  })
    .then((res) => {
      if (!res.ok) {
        console.error(`[fbrefly] /api/clearance POST failed: HTTP ${res.status}`);
        persistStatus("err");
      } else {
        console.log("[fbrefly] cf_clearance delivered to work_server.");
        persistStatus("ok");
      }
    })
    .catch((err) => {
      console.error("[fbrefly] /api/clearance POST error:", err);
      persistStatus("err");
    });
});

// ---------------------------------------------------------------------------
// Task poll loop
// ---------------------------------------------------------------------------

async function pollNextTask() {
  if (_fatalStop) return;

  const configReady = await loadConfig();
  if (!configReady) {
    console.warn("[fbrefly] Poll skipped — work_server_url or work_server_token not set.");
    return;
  }

  let tasksRes;
  try {
    tasksRes = await fetch(`${_config.work_server_url}/api/tasks/next`, {
      headers: authHeaders(),
    });
  } catch (err) {
    const nextBackoff = Math.min(_backoffMs * 2, BACKOFF_CAP_MS);
    console.warn(`[fbrefly] /api/tasks/next network error (backoff ${_backoffMs}ms):`, err);
    _backoffMs = nextBackoff;
    persistStatus("err");
    return;
  }

  if (tasksRes.status === 401 || tasksRes.status === 403) {
    console.error(`[fbrefly] Fatal auth error on /api/tasks/next: HTTP ${tasksRes.status}. Stopping poll loop.`);
    await setFatalStop();
    return;
  }

  if (tasksRes.status === 204) {
    // No tasks — idle, normal cadence.
    _backoffMs = BACKOFF_BASE_MS;
    persistStatus("ok");
    return;
  }

  if (tasksRes.status >= 500) {
    const nextBackoff = Math.min(_backoffMs * 2, BACKOFF_CAP_MS);
    console.warn(`[fbrefly] /api/tasks/next server error HTTP ${tasksRes.status} (backoff ${_backoffMs}ms).`);
    _backoffMs = nextBackoff;
    persistStatus("err");
    return;
  }

  if (!tasksRes.ok) {
    console.warn(`[fbrefly] /api/tasks/next unexpected status: ${tasksRes.status}`);
    _backoffMs = BACKOFF_BASE_MS;
    return;
  }

  // 200 — task available.
  _backoffMs = BACKOFF_BASE_MS;
  persistStatus("ok");

  let task;
  try {
    task = await tasksRes.json();
  } catch (err) {
    console.error("[fbrefly] Failed to parse task JSON:", err);
    return;
  }

  const { id, url } = task;
  if (!id || !url) {
    console.error("[fbrefly] Task missing id or url:", task);
    return;
  }

  await executeFetchTask(id, url);
}

async function executeFetchTask(taskId, taskUrl) {
  let html;
  let httpStatus;

  try {
    const pageRes = await fetch(taskUrl, { credentials: "include" });
    httpStatus = pageRes.status;

    if (!pageRes.ok) {
      // Non-2xx: report error to work_server.
      await postTaskResult(taskId, {
        html: null,
        status: httpStatus,
        error: `Fetch returned HTTP ${httpStatus}`,
      });
      return;
    }

    html = await pageRes.text();
  } catch (err) {
    console.warn(`[fbrefly] fetch(${taskUrl}) failed:`, err);
    await postTaskResult(taskId, {
      html: null,
      status: null,
      error: String(err),
    });
    return;
  }

  await postTaskResult(taskId, { html, status: httpStatus });
}

async function postTaskResult(taskId, payload) {
  const url = `${_config.work_server_url}/api/tasks/${taskId}/result`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      console.error(`[fbrefly] /api/tasks/${taskId}/result POST failed: HTTP ${res.status}`);
    }
  } catch (err) {
    console.error(`[fbrefly] /api/tasks/${taskId}/result POST error:`, err);
  }
}

// ---------------------------------------------------------------------------
// Alarm registration
// ---------------------------------------------------------------------------

async function startAlarmIfNeeded() {
  const existing = await chrome.alarms.get(ALARM_NAME);
  if (!existing) {
    chrome.alarms.create(ALARM_NAME, { periodInMinutes: ALARM_PERIOD_MINUTES });
    console.log(`[fbrefly] Alarm "${ALARM_NAME}" created (period: ${ALARM_PERIOD_MINUTES} min).`);
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    pollNextTask().catch((err) => {
      console.error("[fbrefly] Unhandled error in pollNextTask:", err);
      persistStatus("error");
    });
  }
});

// ---------------------------------------------------------------------------
// Service worker lifecycle
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async () => {
  console.log("[fbrefly] Extension installed/updated.");
  await loadConfig();
  await startAlarmIfNeeded();
});

chrome.runtime.onStartup.addListener(async () => {
  console.log("[fbrefly] Browser startup — ensuring alarm is active.");
  await loadConfig();
  await startAlarmIfNeeded();
});
