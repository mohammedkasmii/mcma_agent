/*
 * mcma.web.app -- hardened vanilla JavaScript dashboard (INC-19).
 * No build step, no TypeScript, no framework. Every render path builds
 * DOM nodes via document.createElement + .textContent -- claimant-
 * controlled data is NEVER assigned to .innerHTML or interpolated into
 * an HTML string. Pure, DOM-free helpers are attached to
 * window.mcmaDashboard so tests can call them directly (Playwright
 * against this exact file, tests/web/*).
 *
 * Out of scope, structurally: this file contains no Enregistrer/Valider/
 * Cloture/GED control and no function that could construct one -- final
 * portal validation is a human action performed directly in the real
 * SinAuto portal, never from this dashboard.
 */

(function () {
  "use strict";

  // ----------------------------------------------------------------- //
  // Escaping / safe rendering -- never innerHTML with untrusted content
  // ----------------------------------------------------------------- //

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = String(value == null ? "" : value);
    return div.innerHTML;
  }

  function setText(el, value) {
    el.textContent = value == null ? "" : String(value);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) setText(node, text);
    return node;
  }

  // ----------------------------------------------------------------- //
  // Notifications -- account-labelled, built via createElement/textContent
  // ----------------------------------------------------------------- //

  function accountLabelText(notification) {
    var entity = notification.account_entity || "?";
    var scope = notification.account_scope || "?";
    return entity + " / " + scope;
  }

  function renderNotificationRow(notification) {
    var row = el("li", "notification-row");
    var badge = el("span", "account-badge", accountLabelText(notification));
    var reference = el("span", "notification-reference", notification.reference || "(no reference)");
    var seenAt = el("span", "notification-seen-at", notification.seen_at || "");
    row.appendChild(badge);
    row.appendChild(reference);
    row.appendChild(seenAt);
    return row;
  }

  function renderNotificationList(container, notifications) {
    container.textContent = ""; // clear without innerHTML
    if (!notifications || notifications.length === 0) {
      container.appendChild(el("li", "empty-state", "No notifications."));
      return;
    }
    notifications.forEach(function (n) {
      container.appendChild(renderNotificationRow(n));
    });
  }

  // ----------------------------------------------------------------- //
  // Truthful readiness -- labels come ONLY from the real job status the
  // server returned; there is no try/finally fallback that could set a
  // "ready"-sounding label regardless of outcome, and no code path
  // derives readiness from a file's mere existence.
  // ----------------------------------------------------------------- //

  var STATUS_LABELS = {
    QUEUED: "Queued",
    PLANNING: "Planning",
    PLANNED: "Planned",
    NEEDS_REVIEW: "Needs review before it can proceed",
    READ_ONLY_IDENTITY_CHECK: "Checking mission identity",
    DRY_RUN_VERIFIED: "Dry-run verified -- ready to authorize execution",
    IDENTITY_FAILED: "Identity check failed",
    ACQUIRING_ACCOUNT_LOCK: "Acquiring account lock",
    IDENTITY_VERIFYING: "Verifying identity",
    IDENTITY_VERIFIED: "Identity verified",
    WRITING: "Writing to the portal",
    VERIFYING: "Verifying the write",
    WRITE_ABORTED: "Write aborted -- needs human review",
    READY_FOR_HUMAN_REVIEW: "Ready for your review -- browser is open",
    AWAITING_HUMAN_CONFIRMATION: "Browser closed -- awaiting your confirmation",
    HUMAN_CONFIRMED_COMPLETE: "Completed (you confirmed this)",
    INTERRUPTED_NEEDS_HUMAN_REVIEW: "Interrupted -- needs human review",
    ABORTED_ON_RESTART: "Aborted on restart",
    ERROR: "Error",
  };

  var SUCCESS_STATUSES = ["READY_FOR_HUMAN_REVIEW", "AWAITING_HUMAN_CONFIRMATION", "HUMAN_CONFIRMED_COMPLETE"];

  function readinessLabel(status) {
    if (Object.prototype.hasOwnProperty.call(STATUS_LABELS, status)) {
      return STATUS_LABELS[status];
    }
    return "Unknown status: " + String(status); // truthful, never a default success label
  }

  function isReadyLooking(status) {
    return SUCCESS_STATUSES.indexOf(status) !== -1;
  }

  async function updateReadinessDisplay(fetchImpl, labelEl, jobId) {
    try {
      var response = await fetchImpl("/jobs?job_id=" + encodeURIComponent(jobId), { credentials: "include" });
      if (!response.ok) {
        setText(labelEl, "Status unavailable (HTTP " + response.status + ")");
        return;
      }
      var data = await response.json();
      var job = (data.jobs || []).find(function (j) {
        return j.job_id === jobId;
      });
      if (!job) {
        setText(labelEl, "Job not found");
        return;
      }
      setText(labelEl, readinessLabel(job.status));
    } catch (err) {
      // NO finally block sets a ready label here -- a fetch failure is
      // reported as an explicit error state, never "ready".
      setText(labelEl, "Status unavailable -- check connection");
    }
  }

  // ----------------------------------------------------------------- //
  // No sample/demo data -- every render path starts from an explicit
  // "loading"/"error"/"empty" state, never a hardcoded example record.
  // ----------------------------------------------------------------- //

  var SAMPLE_DATA = null; // structurally absent -- there is no demo dataset in this file

  function renderLoadingState(container) {
    container.textContent = "";
    container.appendChild(el("p", "loading-state", "Loading..."));
  }

  function renderErrorState(container, message) {
    container.textContent = "";
    container.appendChild(el("p", "error-state", message || "Something went wrong."));
  }

  // ----------------------------------------------------------------- //
  // Authenticated + CSRF-protected action calls
  // ----------------------------------------------------------------- //

  function readCsrfCookie() {
    var match = document.cookie.match(/(?:^|; )mcma_csrf=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function postAction(fetchImpl, path, body) {
    return fetchImpl(path, {
      method: "POST",
      credentials: "include", // always sends the session cookie
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": readCsrfCookie(), // never omitted on a state-changing call
      },
      body: JSON.stringify(body || {}),
    });
  }

  async function submitJsonDossier(fetchImpl, accountId, workflowName, parsedJson) {
    return postAction(fetchImpl, "/jobs/dry-runs", {
      account_id: accountId,
      workflow_name: workflowName,
      typed_input: parsedJson,
      idempotency_key: (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : String(Date.now()),
    });
  }

  async function confirmReviewCompleted(fetchImpl, jobId) {
    return postAction(fetchImpl, "/jobs/" + encodeURIComponent(jobId) + "/review-completed", {});
  }

  async function reportProblem(fetchImpl, jobId, reasonCode) {
    return postAction(fetchImpl, "/jobs/" + encodeURIComponent(jobId) + "/problem", { reason_code: reasonCode });
  }

  // ----------------------------------------------------------------- //
  // Manual JSON dossier upload (section H) -- reads the local file,
  // parses/validates it client-side, never retains the file path/name
  // beyond the upload flow, never logs its content.
  // ----------------------------------------------------------------- //

  var MAX_DOSSIER_BYTES = 5 * 1024 * 1024; // 5 MB -- generous for a JSON dossier, rejects an oversized file

  function parseDossierFileText(text) {
    if (!text || text.length === 0) {
      throw new Error("empty file");
    }
    var parsed = JSON.parse(text); // throws on malformed JSON
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("not a JSON object");
    }
    return parsed;
  }

  function readDossierFile(file) {
    return new Promise(function (resolve, reject) {
      if (!file) {
        reject(new Error("no file selected"));
        return;
      }
      if (file.size === 0) {
        reject(new Error("empty file"));
        return;
      }
      if (file.size > MAX_DOSSIER_BYTES) {
        reject(new Error("file too large"));
        return;
      }
      var reader = new FileReader();
      reader.onerror = function () {
        reject(new Error("could not read file"));
      };
      reader.onload = function () {
        try {
          resolve(parseDossierFileText(String(reader.result)));
        } catch (err) {
          reject(err);
        }
      };
      reader.readAsText(file);
    });
  }

  // ----------------------------------------------------------------- //
  // Export -- testable surface
  // ----------------------------------------------------------------- //

  // ----------------------------------------------------------------- //
  // Page wiring -- only runs against elements that actually exist, so
  // loading this file standalone (as the tests do) never throws.
  // ----------------------------------------------------------------- //

  function init() {
    var notificationsEl = document.getElementById("notifications-list");
    var loginForm = document.getElementById("login-form");
    var uploadForm = document.getElementById("dossier-upload-form");
    var reviewCompletedBtn = document.getElementById("review-completed-btn");
    var problemBtn = document.getElementById("problem-btn");

    async function refreshNotifications() {
      if (!notificationsEl) return;
      renderLoadingState(notificationsEl);
      try {
        var response = await fetch("/notifications", { credentials: "include" });
        if (!response.ok) {
          renderErrorState(notificationsEl, "Could not load notifications (HTTP " + response.status + ")");
          return;
        }
        var data = await response.json();
        renderNotificationList(notificationsEl, data.notifications);
      } catch (err) {
        renderErrorState(notificationsEl, "Could not load notifications -- check connection");
      }
    }

    if (loginForm) {
      loginForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        var username = document.getElementById("login-username").value;
        var password = document.getElementById("login-password").value;
        var response = await fetch("/auth/login", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username, password: password }),
        });
        var statusEl = document.getElementById("login-status");
        if (response.ok) {
          setText(statusEl, "Logged in.");
          refreshNotifications();
        } else {
          setText(statusEl, "Login failed.");
        }
      });
    }

    if (uploadForm) {
      uploadForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        var statusEl = document.getElementById("upload-status");
        var fileInput = document.getElementById("dossier-file-input");
        var accountSelect = document.getElementById("account-select");
        try {
          var parsed = await readDossierFile(fileInput.files[0]);
          var response = await submitJsonDossier(fetch, accountSelect.value, "mission_normal", parsed);
          if (response.ok) {
            setText(statusEl, "Dry-run created. Review the plan before authorizing execution.");
          } else {
            var body = await response.json();
            setText(statusEl, "Rejected: " + (body.error || "unknown error"));
          }
        } catch (err) {
          setText(statusEl, "Could not read/parse the selected file: " + err.message);
        }
      });
    }

    if (reviewCompletedBtn) {
      reviewCompletedBtn.addEventListener("click", async function () {
        var jobId = reviewCompletedBtn.getAttribute("data-job-id");
        var response = await confirmReviewCompleted(fetch, jobId);
        var statusEl = document.getElementById("handoff-status");
        setText(statusEl, response.ok ? "Marked completed (your confirmation)." : "Could not confirm completion.");
      });
    }

    if (problemBtn) {
      problemBtn.addEventListener("click", async function () {
        var jobId = problemBtn.getAttribute("data-job-id");
        var response = await reportProblem(fetch, jobId, "EMPLOYEE_REPORTED_PROBLEM");
        var statusEl = document.getElementById("handoff-status");
        setText(statusEl, response.ok ? "Problem reported -- needs human review." : "Could not report the problem.");
      });
    }

    refreshNotifications();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.mcmaDashboard = {
    escapeHtml: escapeHtml,
    setText: setText,
    el: el,
    accountLabelText: accountLabelText,
    renderNotificationRow: renderNotificationRow,
    renderNotificationList: renderNotificationList,
    readinessLabel: readinessLabel,
    isReadyLooking: isReadyLooking,
    updateReadinessDisplay: updateReadinessDisplay,
    renderLoadingState: renderLoadingState,
    renderErrorState: renderErrorState,
    SAMPLE_DATA: SAMPLE_DATA,
    readCsrfCookie: readCsrfCookie,
    postAction: postAction,
    submitJsonDossier: submitJsonDossier,
    confirmReviewCompleted: confirmReviewCompleted,
    reportProblem: reportProblem,
    parseDossierFileText: parseDossierFileText,
    readDossierFile: readDossierFile,
  };
})();
