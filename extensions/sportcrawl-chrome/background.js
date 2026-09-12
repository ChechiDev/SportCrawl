/**
 * background.js — SportCrawl MV3 service worker
 *
 * Responsibilities:
 *   1. CF clearance capture: listen for cf_clearance cookie on the configured clearance domain, POST to work_server.
 *   2. Task poll loop: chrome.alarms fires every 1 min, polls for the next task, executes, posts result.
 *   3. Auth: every outbound request carries Authorization: Bearer {token}.
 *   4. Backoff: exponential on 5xx / network errors (base 2s, x2, cap 60s); reset on success.
 *   5. Fatal stop: 401/403 → log error, stop polling (bad token, manual fix required).
 */

const ALARM_NAME = "fetchTaskPoll";
const ALARM_PERIOD_MINUTES = 1;
const KEEPALIVE_ALARM_NAME = "swKeepalive";
const KEEPALIVE_PERIOD_MINUTES = 0.5; // Chrome MV3 minimum; fires every 30s to prevent idle SW termination
const BACKOFF_BASE_MS = 2000;
const BACKOFF_CAP_MS = 60000;

let _config = { work_server_url: "", work_server_token: "", profile_id: "", worker_id: "", disable_task_polling: false, enable_sw_keepalive: false };
let _allowedClearanceDomain = ""; // kept separate from _config to allow independent reset during service worker restart
let _backoffMs = BACKOFF_BASE_MS;
let _fatalStop = false;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

/**
 * Load runtime config from chrome.storage.local (device-local, never synced).
 * Returns true when both url and token are present; false otherwise.
 */
async function loadConfig() {
  const { fatalStop } = await chrome.storage.local.get("fatalStop");
  _fatalStop = !!fatalStop;

  return new Promise((resolve) => {
    chrome.storage.local.get(
      { work_server_url: "", work_server_token: "", profile_id: "", worker_id: "", disable_task_polling: false, enable_sw_keepalive: false, allowed_clearance_domain: "" },
      (data) => {
        _config = {
          work_server_url: data.work_server_url.trim(),
          work_server_token: data.work_server_token.trim(),
          profile_id: data.profile_id.trim(),
          worker_id: data.worker_id.trim(),
          disable_task_polling: !!data.disable_task_polling,
          enable_sw_keepalive: !!data.enable_sw_keepalive,
        };
        _allowedClearanceDomain = (data.allowed_clearance_domain || "").trim().replace(/^\./, "");
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
  await chrome.alarms.clear(KEEPALIVE_ALARM_NAME);
  persistStatus("fatal");
}

// ---------------------------------------------------------------------------
// Runtime readiness
// ---------------------------------------------------------------------------

/** Returns true when all required runtime config fields are present. */
function _isRuntimeReady() {
  return _config.work_server_url !== "" && _config.work_server_token !== "";
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

/**
 * Classify a fetch() rejection into a stable operational error code.
 * Avoids exposing raw err.name as an operational signal.
 * @param {Error|null} err
 * @returns {string}
 */
function _classifyFetchError(err) {
  if (err && err.name === "AbortError") return "aborted";
  if (err && err.name === "TypeError") return "network_error";
  return "fetch_error";
}

/**
 * Classify an HTTP status code into a coarse bucket string.
 * @param {number} status
 * @returns {string}
 */
function _classifyHttpStatus(status) {
  if (status < 300) return "2xx";
  if (status < 400) return "3xx";
  if (status < 500) return "4xx";
  return "5xx";
}

/**
 * Boundary-safe domain suffix check.
 * Matches exact, dot-prefixed (.example.com), or subdomain (sub.example.com).
 */
function _domainMatches(cookieDomain, allowedDomain) {
  if (!allowedDomain) return false;
  return cookieDomain === allowedDomain
    || cookieDomain === "." + allowedDomain
    || cookieDomain.endsWith("." + allowedDomain);
}

chrome.cookies.onChanged.addListener(async (details) => {
  await loadConfig(); // reload config in case SW was terminated and restarted
  const cookie = details.cookie;

  if (cookie.name !== "cf_clearance" || details.removed) {
    return;
  }
  if (!_allowedClearanceDomain) {
    try {
      chrome.storage.local.set({
        last_clearance_post_status: {
          attempted: false,
          drop_reason: "CLEARANCE_DOMAIN_NOT_CONFIGURED",
          timestamp_ms: Date.now(),
        },
      }).catch(() =>
        console.warn("[SportCrawl] diagnostic write failed: storage write failed")
      );
    } catch (_e) {
      console.warn("[SportCrawl] diagnostic write failed: storage write failed");
    }
    console.warn("[SportCrawl] cookie listener skipped: clearance domain not configured");
    return;
  }
  if (!_domainMatches(cookie.domain, _allowedClearanceDomain)) {
    return;
  }

  if (!_isRuntimeReady()) {
    console.warn("[SportCrawl] Runtime configuration incomplete — skipping clearance POST.");
    return;
  }

  // Validate explicit operational identifiers — must be configured, not derived.
  const _ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
  if (!_config.profile_id || !_ID_RE.test(_config.profile_id)) {
    console.warn("[SportCrawl] profile_id missing or invalid — skipping clearance POST.");
    return;
  }
  if (!_config.worker_id || !_ID_RE.test(_config.worker_id)) {
    console.warn("[SportCrawl] worker_id missing or invalid — skipping clearance POST.");
    return;
  }

  // Validate cookie expiry — must be present and in the future.
  const expirationDate = cookie.expirationDate;
  if (
    typeof expirationDate !== "number" ||
    !isFinite(expirationDate) ||
    expirationDate * 1000 <= Date.now()
  ) {
    console.warn("[SportCrawl] Cookie expiry missing or already past — skipping clearance POST.");
    return;
  }

  const observed_at = new Date().toISOString();
  const expires_at = new Date(expirationDate * 1000).toISOString();

  const url = `${_config.work_server_url}/api/clearance`;
  // SW termination window: chrome.cookies.onChanged is not an ExtendableEvent,
  // so event.waitUntil() is unavailable here. The diagnostic write may be lost if
  // the SW is terminated after the fetch resolves but before the storage write
  // completes. A harness should treat a missing or stale last_clearance_post_status
  // as inconclusive rather than a confirmed failure.
  fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      domain: cookie.domain,
      profile_id: _config.profile_id,
      worker_id: _config.worker_id,
      observed_at: observed_at,
      expires_at: expires_at,
      clearance: cookie.value,
    }),
  })
    .then((res) => {
      if (!res.ok) {
        console.error(`[SportCrawl] /api/clearance POST failed: HTTP ${res.status}`);
        persistStatus("err");
      } else {
        console.log("[SportCrawl] Clearance delivered to work_server.");
        persistStatus("ok");
      }
      // Durable diagnostic — no sensitive values included.
      const cls = _classifyHttpStatus(res.status);
      try {
        chrome.storage.local.set({
          last_clearance_post_status: {
            attempted: true,
            http_status_class: cls,
            error_class: null,
            timestamp_ms: Date.now(),
          },
        }).catch(() =>
          console.warn("[SportCrawl] diagnostic write failed: storage write failed")
        );
      } catch (_e) {
        console.warn("[SportCrawl] diagnostic write failed: storage write failed");
      }
    })
    .catch((err) => {
      try {
        chrome.storage.local.set({
          last_clearance_post_status: {
            attempted: true,
            http_status_class: "network_error",
            error_class: _classifyFetchError(err),
            timestamp_ms: Date.now(),
          },
        }).catch(() =>
          console.warn("[SportCrawl] diagnostic write failed: storage write failed")
        );
      } catch (_e) {
        console.warn("[SportCrawl] diagnostic write failed: storage write failed");
      }
      console.error("[SportCrawl] /api/clearance POST error:", err);
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
    console.warn("[SportCrawl] Runtime configuration incomplete — skipping poll.");
    return;
  }

  if (_config.disable_task_polling) {
    return;
  }

  let tasksRes;
  try {
    tasksRes = await fetch(`${_config.work_server_url}/api/tasks/next`, {
      headers: authHeaders(),
    });
  } catch (err) {
    const nextBackoff = Math.min(_backoffMs * 2, BACKOFF_CAP_MS);
    console.warn(`[SportCrawl] /api/tasks/next network error (backoff ${_backoffMs}ms):`, err);
    _backoffMs = nextBackoff;
    persistStatus("err");
    return;
  }

  if (tasksRes.status === 401 || tasksRes.status === 403) {
    console.error(`[SportCrawl] Fatal auth error on /api/tasks/next: HTTP ${tasksRes.status}. Stopping poll loop.`);
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
    console.warn(`[SportCrawl] /api/tasks/next server error HTTP ${tasksRes.status} (backoff ${_backoffMs}ms).`);
    _backoffMs = nextBackoff;
    persistStatus("err");
    return;
  }

  if (!tasksRes.ok) {
    console.warn(`[SportCrawl] /api/tasks/next unexpected status: ${tasksRes.status}`);
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
    console.error("[SportCrawl] Failed to parse task JSON:", err);
    return;
  }

  const { id, url } = task;
  if (!id || !url) {
    console.error("[SportCrawl] Task missing id or url:", task);
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
    console.warn(`[SportCrawl] fetch(${taskUrl}) failed:`, err);
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
      console.error(`[SportCrawl] /api/tasks/${taskId}/result POST failed: HTTP ${res.status}`);
    }
  } catch (err) {
    console.error(`[SportCrawl] /api/tasks/${taskId}/result POST error:`, err);
  }
}

// ---------------------------------------------------------------------------
// Alarm registration
// ---------------------------------------------------------------------------

async function startAlarmIfNeeded() {
  if (_config.disable_task_polling) {
    await chrome.alarms.clear(ALARM_NAME);
  } else {
    const existing = await chrome.alarms.get(ALARM_NAME);
    if (!existing) {
      chrome.alarms.create(ALARM_NAME, { periodInMinutes: ALARM_PERIOD_MINUTES });
      console.log(`[SportCrawl] Alarm "${ALARM_NAME}" created (period: ${ALARM_PERIOD_MINUTES} min).`);
    }
  }
  if (_config.enable_sw_keepalive) {
    const existing = await chrome.alarms.get(KEEPALIVE_ALARM_NAME);
    if (!existing) {
      chrome.alarms.create(KEEPALIVE_ALARM_NAME, { periodInMinutes: KEEPALIVE_PERIOD_MINUTES });
      console.log(`[SportCrawl] Keepalive alarm "${KEEPALIVE_ALARM_NAME}" created.`);
    }
  } else {
    await chrome.alarms.clear(KEEPALIVE_ALARM_NAME);
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    pollNextTask().catch((err) => {
      console.error("[SportCrawl] Unhandled error in pollNextTask:", err);
      persistStatus("error");
    });
  }
  if (alarm.name === KEEPALIVE_ALARM_NAME) {
    // No-op: alarm fire is sufficient to keep the service worker alive.
  }
});

// ---------------------------------------------------------------------------
// Service worker lifecycle
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async () => {
  console.log("[SportCrawl] Extension installed/updated.");
  await loadConfig();
  await startAlarmIfNeeded();
});

chrome.runtime.onStartup.addListener(async () => {
  console.log("[SportCrawl] Browser startup — ensuring alarm is active.");
  await loadConfig();
  await startAlarmIfNeeded();
});
