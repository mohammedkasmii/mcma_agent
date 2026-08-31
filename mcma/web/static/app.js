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

  // ----------------------------------------------------------------- //
  // Claims -- the employee's working list for ONE account at a time.
  // Every node is built with createElement/textContent, never innerHTML:
  // claim references, insured names and notes are portal-supplied or
  // employee-typed text and must never be parsed as markup.
  // ----------------------------------------------------------------- //

  var CLAIM_STATUSES = ["NEW", "IN_PROGRESS", "WAITING", "DONE", "NOT_APPLICABLE"];
  var CLAIM_STATUS_LABELS = {
    NEW: "New",
    IN_PROGRESS: "In progress",
    WAITING: "Waiting",
    DONE: "Done",
    NOT_APPLICABLE: "Not applicable"
  };

  function renderClaimRow(claim, onSave) {
    var row = el("li", "claim-row");

    var head = el("div", "claim-head");
    head.appendChild(el("span", "claim-reference", claim.reference || claim.portal_claim_id || "(no reference)"));
    var pill = el("span", "claim-pill claim-pill-" + (claim.status || "NEW"),
                  CLAIM_STATUS_LABELS[claim.status] || claim.status || "New");
    head.appendChild(pill);
    row.appendChild(head);

    if (claim.insured || claim.matricule_norm) {
      var meta = el("div", "claim-meta");
      if (claim.insured) meta.appendChild(el("span", "claim-insured", claim.insured));
      if (claim.matricule_norm) meta.appendChild(el("span", "claim-matricule", claim.matricule_norm));
      row.appendChild(meta);
    }

    if (claim.categories && claim.categories.length) {
      var cats = el("div", "claim-categories");
      claim.categories.forEach(function (label) {
        cats.appendChild(el("span", "claim-category", label));
      });
      row.appendChild(cats);
    }

    var controls = el("div", "claim-controls");

    var select = document.createElement("select");
    select.className = "claim-status-select";
    select.setAttribute("aria-label", "Status");
    CLAIM_STATUSES.forEach(function (value) {
      var option = document.createElement("option");
      option.value = value;
      setText(option, CLAIM_STATUS_LABELS[value]);
      if (value === (claim.status || "NEW")) option.selected = true;
      select.appendChild(option);
    });
    controls.appendChild(select);

    var noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.className = "claim-note-input";
    noteInput.maxLength = 2000;
    noteInput.placeholder = "Add a note";
    noteInput.value = claim.note || "";
    noteInput.setAttribute("aria-label", "Note");
    controls.appendChild(noteInput);

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "primary claim-save";
    setText(saveBtn, "Save");
    controls.appendChild(saveBtn);

    var saved = el("span", "claim-saved", "");
    controls.appendChild(saved);
    row.appendChild(controls);

    saveBtn.addEventListener("click", async function () {
      saveBtn.disabled = true;
      setText(saved, "Saving...");
      var ok = await onSave(claim.claim_pk, select.value, noteInput.value);
      saveBtn.disabled = false;
      if (ok) {
        setText(saved, "Saved");
        setText(pill, CLAIM_STATUS_LABELS[select.value] || select.value);
        pill.className = "claim-pill claim-pill-" + select.value;
      } else {
        setText(saved, "Not saved");
      }
    });

    return row;
  }

  function renderClaimList(container, claims, onSave) {
    container.textContent = "";
    if (!claims || claims.length === 0) {
      container.appendChild(el("li", "empty-state", "No claims for this account yet."));
      return;
    }
    claims.forEach(function (claim) {
      container.appendChild(renderClaimRow(claim, onSave));
    });
  }

  // ----------------------------------------------------------------- //
  // The dashboard proper: KPI cards, category tabs, status filters,
  // search, and the claims table. Ported from the original static/
  // dashboard, with two changes that matter: every cell is built with
  // createElement/textContent instead of innerHTML (portal-supplied
  // sociétaire names and references must never be parsed as markup --
  // see tests/web/test_escaping.py), and everything is scoped to ONE of
  // the four portal accounts at a time.
  // ----------------------------------------------------------------- //

  var ACTION_FILTERS = {
    ALL: function () { return true; },
    TODO: function (c) { return !c.status || c.status === "NEW"; },
    IN_PROGRESS: function (c) { return c.status === "IN_PROGRESS" || c.status === "WAITING"; },
    DONE: function (c) { return c.status === "DONE" || c.status === "NOT_APPLICABLE"; }
  };

  var STATUS_FR = {
    NEW: "À Traiter",
    IN_PROGRESS: "En Cours",
    WAITING: "En Attente",
    DONE: "Traité",
    NOT_APPLICABLE: "Sans Suite"
  };

  function claimMatchesSearch(claim, needle) {
    if (!needle) return true;
    var haystack = [claim.reference, claim.insured, claim.police, claim.matricule_norm,
                    claim.portal_claim_id].join(" ").toLowerCase();
    return haystack.indexOf(needle.toLowerCase()) !== -1;
  }

  function renderKpis(claims) {
    var total = claims.length;
    var done = claims.filter(function (c) { return c.status === "DONE"; }).length;
    var categories = {};
    claims.forEach(function (c) {
      (c.categories || []).forEach(function (cat) { categories[cat] = true; });
    });
    var pct = total ? Math.round((done / total) * 100) : 0;

    function put(id, value) {
      var node = document.getElementById(id);
      if (node) setText(node, value);
    }

    put("kpiTotal", String(total));
    put("kpiTodo", String(total - done));
    put("kpiCategories", String(Object.keys(categories).length));

    // kpiDone CONTAINS the percentage span, so its text cannot simply be
    // replaced -- doing that removes the span before it can be written.
    var doneEl = document.getElementById("kpiDone");
    var pctEl = document.getElementById("kpiProgressPct");
    if (doneEl) {
      doneEl.textContent = String(done) + " ";
      if (pctEl) {
        setText(pctEl, "(" + pct + "%)");
        doneEl.appendChild(pctEl);
      }
    }
  }

  function renderCategoryTabs(container, claims, selected, onSelect) {
    if (!container) return;
    var counts = {};
    claims.forEach(function (c) {
      (c.categories || []).forEach(function (cat) { counts[cat] = (counts[cat] || 0) + 1; });
    });
    container.textContent = "";

    function tab(label, count, value) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "tab-btn" + (value === selected ? " active" : "");
      setText(button, label + " ");
      var badge = el("span", "tab-badge", String(count));
      button.appendChild(badge);
      button.addEventListener("click", function () { onSelect(value); });
      return button;
    }

    container.appendChild(tab("Toutes les alertes", claims.length, "ALL"));
    Object.keys(counts).sort().forEach(function (cat) {
      container.appendChild(tab(cat, counts[cat], cat));
    });
  }

  function renderClaimsTable(tbody, claims, onEdit) {
    tbody.textContent = "";
    claims.forEach(function (claim) {
      var tr = document.createElement("tr");

      var suivi = document.createElement("td");
      var pill = el("span", "status-badge claim-pill-" + (claim.status || "NEW"),
                    STATUS_FR[claim.status] || STATUS_FR.NEW);
      suivi.appendChild(pill);
      var edit = document.createElement("button");
      edit.type = "button";
      edit.className = "btn-icon";
      setText(edit, "\u270e");
      edit.title = "Modifier le suivi";
      edit.addEventListener("click", function () { onEdit(claim); });
      suivi.appendChild(edit);
      tr.appendChild(suivi);

      function cell(value, className) {
        var td = document.createElement("td");
        if (className) td.className = className;
        setText(td, value == null || value === "" ? "\u2014" : String(value));
        return td;
      }

      tr.appendChild(cell(claim.reference || claim.portal_claim_id, "cell-ref"));
      tr.appendChild(cell(claim.updated_at));
      tr.appendChild(cell(claim.insured, "cell-name"));
      tr.appendChild(cell(claim.police));
      tr.appendChild(cell(claim.matricule_norm, "cell-mono"));
      tr.appendChild(cell((claim.categories || []).join(", ")));
      tr.appendChild(cell(claim.note));
      tbody.appendChild(tr);
    });
  }

  function renderAccountBar(container, accounts, selectedId, onSelect, onConnect) {
    if (!container) return;
    container.textContent = "";
    accounts.forEach(function (account) {
      var isMamda = account.entity === "MAMDA";
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "account-chip"
        + (isMamda ? " account-chip-mamda" : "")
        + (account.account_id === selectedId ? " account-chip-active" : "");
      chip.setAttribute("role", "tab");
      chip.setAttribute("aria-selected", account.account_id === selectedId ? "true" : "false");

      chip.appendChild(el("span", "account-session-dot"
        + (account.session_active ? " account-session-dot-live" : "")));
      chip.appendChild(el("span", null, (account.entity || "?") + " " + (account.scope || "?")));
      if (isMamda) {
        // Visible, permanently: a MAMDA account can be read but a form
        // job can never be started against one.
        chip.appendChild(el("span", "account-readonly-tag", "lecture seule"));
      }
      chip.addEventListener("click", function () { onSelect(account.account_id); });

      if (!account.session_active) {
        var connect = document.createElement("button");
        connect.type = "button";
        connect.className = "account-chip-connect";
        setText(connect, "connexion");
        connect.addEventListener("click", function (event) {
          // The chip itself selects; this selects AND signs in.
          event.stopPropagation();
          onSelect(account.account_id);
          if (typeof onConnect === "function") onConnect(account.account_id);
        });
        chip.appendChild(connect);
      }
      container.appendChild(chip);
    });
  }

  function renderAccountTabs(container, accounts, selectedId, onSelect) {
    container.textContent = "";
    accounts.forEach(function (account) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "tab" + (account.account_id === selectedId ? " tab-selected" : "");
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", account.account_id === selectedId ? "true" : "false");
      setText(button, (account.entity || "?") + " " + (account.scope || "?"));
      button.addEventListener("click", function () { onSelect(account.account_id); });
      container.appendChild(button);
    });
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

  async function fetchJobById(fetchImpl, jobId) {
    var response = await fetchImpl("/jobs?job_id=" + encodeURIComponent(jobId), { credentials: "include" });
    if (!response.ok) {
      return { ok: false, status: response.status, job: null };
    }
    var data = await response.json();
    var job = (data.jobs || []).find(function (j) {
      return j.job_id === jobId;
    });
    return { ok: true, status: response.status, job: job || null };
  }

  async function updateReadinessDisplay(fetchImpl, labelEl, jobId) {
    try {
      var result = await fetchJobById(fetchImpl, jobId);
      if (!result.ok) {
        setText(labelEl, "Status unavailable (HTTP " + result.status + ")");
        return null;
      }
      if (!result.job) {
        setText(labelEl, "Job not found");
        return null;
      }
      setText(labelEl, readinessLabel(result.job.status));
      return result.job;
    } catch (err) {
      // NO finally block sets a ready label here -- a fetch failure is
      // reported as an explicit error state, never "ready".
      setText(labelEl, "Status unavailable -- check connection");
      return null;
    }
  }

  // ----------------------------------------------------------------- //
  // Plan preview -- built via createElement/textContent only, exactly
  // like renderNotificationRow. No charge-mutuelle/sociétaire field ever
  // appears here (ProposedPlan/plan_snapshot structurally cannot carry
  // one -- see mcma.planning.plan.RowOp's own docstring).
  // ----------------------------------------------------------------- //

  function renderPlanPreview(container, job) {
    container.textContent = "";
    if (!job || !job.plan_snapshot) {
      container.appendChild(el("p", "empty-state", "No plan yet."));
      return;
    }
    var plan;
    try {
      plan = JSON.parse(job.plan_snapshot);
    } catch (err) {
      container.appendChild(el("p", "error-state", "Plan preview unavailable."));
      return;
    }
    var steps = plan.steps || [];
    var needsReview = plan.needs_review || [];
    container.appendChild(el("p", "plan-workflow", "Workflow: " + (plan.repair_workflow || "?")));
    var stepsList = el("ul", "plan-steps");
    steps.forEach(function (step) {
      stepsList.appendChild(el("li", "plan-step", "Rubrique " + step.rubrique_id + " -- HT " + step.ht));
    });
    container.appendChild(stepsList);
    var formFieldIntents = plan.form_field_intents || [];
    if (formFieldIntents.length > 0) {
      var fieldsList = el("ul", "plan-form-fields");
      formFieldIntents.forEach(function (intent) {
        fieldsList.appendChild(el("li", "plan-form-field", intent.selector + " = " + intent.value));
      });
      container.appendChild(fieldsList);
    }
    if (needsReview.length > 0) {
      var warnings = el("ul", "plan-warnings");
      needsReview.forEach(function (review) {
        warnings.appendChild(el("li", "plan-warning", review.reason + (review.detail ? ": " + review.detail : "")));
      });
      container.appendChild(warnings);
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

  async function saveClaimAction(fetchImpl, claimPk, status, note) {
    return postAction(fetchImpl, "/claims/" + encodeURIComponent(claimPk) + "/action",
                      { status: status, note: note });
  }

  async function openPortalLogin(fetchImpl, accountId) {
    return postAction(fetchImpl, "/accounts/" + encodeURIComponent(accountId) + "/login", {});
  }

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

  async function submitJsonDossier(fetchImpl, accountId, parsedJson) {
    // Pilot-integration correction (section 3/6): workflow_name is NEVER
    // sent from here -- the server determines it from the uploaded
    // dossier's own typed evidence (mcma.planning.plan.detect_workflow).
    return postAction(fetchImpl, "/jobs/dry-runs", {
      account_id: accountId,
      typed_input: parsedJson,
      idempotency_key: (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : String(Date.now()),
    });
  }

  async function fetchAccessibleAccounts(fetchImpl) {
    var response = await fetchImpl("/accounts", { credentials: "include" });
    if (!response.ok) {
      throw new Error("could not load accessible accounts");
    }
    var data = await response.json();
    return data.accounts || [];
  }

  function populateMcmaAccountSelect(selectEl, accounts) {
    // Pilot-integration correction (section 2/6): no production
    // account_id is ever hardcoded in the HTML -- this is the ONLY
    // place options are added, and only MCMA accounts are offered (a
    // MAMDA account can never be selected for a form job).
    selectEl.textContent = "";
    var placeholder = el("option", null, "Select an account");
    placeholder.setAttribute("value", "");
    selectEl.appendChild(placeholder);
    accounts
      .filter(function (a) {
        return a.entity === "MCMA";
      })
      .forEach(function (a) {
        var option = el("option", null, a.entity + " / " + a.scope);
        option.setAttribute("value", a.account_id);
        selectEl.appendChild(option);
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

  var HANDOFF_VISIBLE_STATUSES = ["READY_FOR_HUMAN_REVIEW", "AWAITING_HUMAN_CONFIRMATION"];
  var AUTHORIZE_VISIBLE_STATUSES = ["DRY_RUN_VERIFIED"];
  var POLL_INTERVAL_MS = 4000;

  function init() {
    var notificationsEl = document.getElementById("notifications-list");
    var loginForm = document.getElementById("login-form");
    var uploadForm = document.getElementById("dossier-upload-form");
    var accountSelect = document.getElementById("account-select");
    var currentJobIdEl = document.getElementById("current-job-id");
    var planPreviewEl = document.getElementById("plan-preview");
    var readinessLabelEl = document.getElementById("readiness-label");
    var authorizeBtn = document.getElementById("authorize-execution-btn");
    var authorizeStatusEl = document.getElementById("authorize-status");
    var reviewCompletedBtn = document.getElementById("review-completed-btn");
    var problemBtn = document.getElementById("problem-btn");
    var handoffStatusEl = document.getElementById("handoff-status");

    // The ONE piece of job-identity state this page tracks -- every
    // button below acts on THIS real job id, never a static/stale one
    // (section 6: "propagate the real job ID").
    var currentJobId = null;
    var pollTimer = null;

    // One account at a time. Selecting a chip re-scopes the KPIs, the
    // category tabs, the table and the form-job target together -- there
    // is no view that mixes two portal accounts.
    var selectedAccountId = null;
    var accounts = [];
    var claims = [];
    var categoryFilter = "ALL";
    var actionFilter = "ALL";
    var searchTerm = "";

    var accountBarEl = document.getElementById("account-bar");
    var categoryTabsEl = document.getElementById("categoryTabs");
    var tableBodyEl = document.getElementById("tableBody");
    var emptyStateEl = document.getElementById("emptyState");
    var searchInputEl = document.getElementById("searchInput");

    function visibleClaims() {
      var passes = ACTION_FILTERS[actionFilter] || ACTION_FILTERS.ALL;
      return claims.filter(function (c) {
        if (categoryFilter !== "ALL" && (c.categories || []).indexOf(categoryFilter) === -1) return false;
        if (!passes(c)) return false;
        return claimMatchesSearch(c, searchTerm);
      });
    }

    function renderAll() {
      renderKpis(claims);
      renderCategoryTabs(categoryTabsEl, claims, categoryFilter, function (value) {
        categoryFilter = value;
        renderAll();
      });
      var rows = visibleClaims();
      if (tableBodyEl) renderClaimsTable(tableBodyEl, rows, openNoteEditor);
      if (emptyStateEl) emptyStateEl.hidden = rows.length !== 0;
    }

    function openNoteEditor(claim) {
      var modal = document.getElementById("noteModal");
      var refEl = document.getElementById("modalClaimRef");
      var statusEl = document.getElementById("modalStatusSelect");
      var noteEl = document.getElementById("modalNoteText");
      if (!modal) return;
      setText(refEl, "Sinistre : " + (claim.reference || claim.portal_claim_id || ""));
      if (statusEl) statusEl.value = claim.status || "NEW";
      if (noteEl) noteEl.value = claim.note || "";
      modal.classList.add("active");
      modal.dataset.claimPk = claim.claim_pk;
    }

    function closeNoteEditor() {
      var modal = document.getElementById("noteModal");
      if (modal) modal.classList.remove("active");
    }

    async function saveNoteFromModal() {
      var modal = document.getElementById("noteModal");
      if (!modal || !modal.dataset.claimPk) return;
      var statusEl = document.getElementById("modalStatusSelect");
      var noteEl = document.getElementById("modalNoteText");
      var response = await saveClaimAction(fetch, modal.dataset.claimPk,
                                           statusEl ? statusEl.value : "NEW",
                                           noteEl ? noteEl.value : "");
      if (response && response.ok) {
        closeNoteEditor();
        await refreshClaims();
      }
    }

    async function refreshClaims() {
      if (!selectedAccountId) return;
      try {
        var response = await fetch("/claims?account_id=" + encodeURIComponent(selectedAccountId),
                                   { credentials: "include" });
        if (!response.ok) {
          claims = [];
          renderAll();
          return;
        }
        var data = await response.json();
        claims = data.claims || [];
        renderAll();
      } catch (err) {
        claims = [];
        renderAll();
      }
    }

    function selectAccount(accountId) {
      selectedAccountId = accountId;
      categoryFilter = "ALL";
      renderAccountBar(accountBarEl, accounts, selectedAccountId, selectAccount, startPortalLogin);
      // The form-job target follows the selected account, and stays
      // MCMA-only: a MAMDA account can never be chosen for a write.
      if (accountSelect) {
        populateMcmaAccountSelect(accountSelect, accounts);
        var selected = accounts.filter(function (a) { return a.account_id === accountId; })[0];
        if (selected && selected.entity === "MCMA") accountSelect.value = accountId;
      }
      refreshClaims();
    }

    async function refreshNotifications() {
      try {
        accounts = await fetchAccessibleAccounts(fetch);
        if (!accounts || accounts.length === 0) {
          renderAccountBar(accountBarEl, [], null, function () {});
          return;
        }
        selectAccount(selectedAccountId || accounts[0].account_id);
      } catch (err) {
        renderAccountBar(accountBarEl, [], null, function () {});
      }
    }

    async function startPortalLogin(accountId) {
      if (!accountId) return;
      var syncText = document.getElementById("syncText");
      var account = accounts.filter(function (a) { return a.account_id === accountId; })[0];
      var label = account ? (account.entity + " " + account.scope) : accountId;
      setText(syncText, "Connexion " + label + " — terminez dans le navigateur");
      try {
        var response = await openPortalLogin(fetch, accountId);
        if (response && response.ok) {
          setText(syncText, "Session " + label + " enregistrée");
          // The dot on the chip is driven by session state, so re-reading
          // the accounts is what makes the result visible.
          await refreshNotifications();
        } else {
          setText(syncText, "Connexion " + label + " non terminée");
        }
      } catch (err) {
        setText(syncText, "Connexion " + label + " impossible");
      }
    }

    function showDashboard() {
      var shell = document.getElementById("app-shell");
      var signin = document.getElementById("login-section");
      if (shell) shell.hidden = false;
      if (signin) signin.hidden = true;
    }

    function wireDashboardControls() {
      document.querySelectorAll("[data-action-filter]").forEach(function (pill) {
        pill.addEventListener("click", function () {
          document.querySelectorAll("[data-action-filter]").forEach(function (p) {
            p.classList.remove("active");
          });
          pill.classList.add("active");
          actionFilter = pill.getAttribute("data-action-filter");
          renderAll();
        });
      });
      if (searchInputEl) {
        searchInputEl.addEventListener("input", function () {
          searchTerm = searchInputEl.value;
          renderAll();
        });
      }
      var clearBtn = document.getElementById("btnClearSearch");
      if (clearBtn && searchInputEl) {
        clearBtn.addEventListener("click", function () {
          searchInputEl.value = "";
          searchTerm = "";
          renderAll();
        });
      }
      var refreshBtn = document.getElementById("btnRefreshLive");
      if (refreshBtn) refreshBtn.addEventListener("click", function () { refreshClaims(); });

      var loginBtn = document.getElementById("btnReauth");
      if (loginBtn) loginBtn.addEventListener("click", function () { startPortalLogin(selectedAccountId); });

      var saveNoteBtn = document.getElementById("btnSaveNote");
      if (saveNoteBtn) saveNoteBtn.addEventListener("click", saveNoteFromModal);
      ["btnCloseModal", "btnCancelNote"].forEach(function (id) {
        var button = document.getElementById(id);
        if (button) button.addEventListener("click", closeNoteEditor);
      });

      // "Importer JSON" in the header is the same upload the hidden form
      // drives -- one code path, two affordances.
      var uploadBtn = document.getElementById("btnUploadFile");
      var headerFile = document.getElementById("fileInput");
      if (uploadBtn && headerFile) {
        uploadBtn.addEventListener("click", function () { headerFile.click(); });
        headerFile.addEventListener("change", function () {
          if (fileInput && headerFile.files && headerFile.files[0]) {
            var transfer = new DataTransfer();
            transfer.items.add(headerFile.files[0]);
            fileInput.files = transfer.files;
          }
          if (uploadForm) uploadForm.dispatchEvent(new Event("submit", { cancelable: true }));
        });
      }
    }

    async function refreshAccounts() {
      if (!accountSelect) return;
      try {
        var accounts = await fetchAccessibleAccounts(fetch);
        populateMcmaAccountSelect(accountSelect, accounts);
      } catch (err) {
        // The select simply stays at its placeholder-only state -- an
        // explicit empty state, never a guessed/hardcoded account list.
      }
    }

    function setHandoffButtonsVisible(job) {
      var visible = job && HANDOFF_VISIBLE_STATUSES.indexOf(job.status) !== -1;
      if (reviewCompletedBtn) reviewCompletedBtn.hidden = !visible;
      if (problemBtn) problemBtn.hidden = !visible;
    }

    function setAuthorizeButtonVisible(job) {
      var visible = job && AUTHORIZE_VISIBLE_STATUSES.indexOf(job.status) !== -1;
      if (authorizeBtn) authorizeBtn.hidden = !visible;
    }

    async function pollCurrentJob() {
      if (!currentJobId || !readinessLabelEl) return;
      var job = await updateReadinessDisplay(fetch, readinessLabelEl, currentJobId);
      if (planPreviewEl) renderPlanPreview(planPreviewEl, job);
      setAuthorizeButtonVisible(job);
      setHandoffButtonsVisible(job);
    }

    function startPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollCurrentJob();
      pollTimer = setInterval(pollCurrentJob, POLL_INTERVAL_MS);
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
          setText(statusEl, "");
          showDashboard();
          refreshNotifications();
          refreshAccounts();
        } else {
          setText(statusEl, "Identifiants incorrects.");
        }
      });
    }

    if (uploadForm) {
      uploadForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        var statusEl = document.getElementById("upload-status");
        var fileInput = document.getElementById("dossier-file-input");
        try {
          if (!accountSelect.value) {
            setText(statusEl, "Select an MCMA account first.");
            return;
          }
          var parsed = await readDossierFile(fileInput.files[0]);
          // workflow_name is never sent -- the server determines it from
          // the uploaded dossier's own typed evidence.
          var response = await submitJsonDossier(fetch, accountSelect.value, parsed);
          var body = await response.json();
          if (response.ok) {
            currentJobId = body.job_id;
            setText(statusEl, "Dry-run created (workflow: " + body.workflow_name + "). Review the plan below.");
            setText(currentJobIdEl, "Current job: " + currentJobId);
            startPolling();
          } else {
            setText(statusEl, "Rejected: " + (body.error || "unknown error"));
          }
        } catch (err) {
          setText(statusEl, "Could not read/parse the selected file: " + err.message);
        }
      });
    }

    if (authorizeBtn) {
      authorizeBtn.addEventListener("click", async function () {
        if (!currentJobId) return;
        var response = await postAction(fetch, "/jobs/" + encodeURIComponent(currentJobId) + "/executions", {});
        var body = await response.json();
        if (response.ok) {
          currentJobId = body.job_id; // the NEW execute job id -- distinct from the dry-run id
          setText(authorizeStatusEl, "Execution authorized (job " + currentJobId + ").");
          setText(currentJobIdEl, "Current job: " + currentJobId);
          startPolling();
        } else {
          setText(authorizeStatusEl, "Could not authorize execution: " + (body.error || "unknown error"));
        }
      });
    }

    if (reviewCompletedBtn) {
      reviewCompletedBtn.addEventListener("click", async function () {
        if (!currentJobId) return;
        var response = await confirmReviewCompleted(fetch, currentJobId);
        setText(handoffStatusEl, response.ok ? "Marked completed (your confirmation)." : "Could not confirm completion.");
        pollCurrentJob();
      });
    }

    if (problemBtn) {
      problemBtn.addEventListener("click", async function () {
        if (!currentJobId) return;
        var response = await reportProblem(fetch, currentJobId, "EMPLOYEE_REPORTED_PROBLEM");
        setText(handoffStatusEl, response.ok ? "Problem reported -- needs human review." : "Could not report the problem.");
        pollCurrentJob();
      });
    }

    wireDashboardControls();
    // The shell stays hidden until a session exists. /accounts is the
    // probe: if it answers, an earlier session is still valid and the
    // employee should not be asked to sign in again.
    (async function () {
      try {
        var probe = await fetch("/accounts", { credentials: "include" });
        if (probe.ok) {
          showDashboard();
          refreshNotifications();
          refreshAccounts();
        }
      } catch (err) {
        // Stay on the sign-in card.
      }
    })();
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
    fetchJobById: fetchJobById,
    updateReadinessDisplay: updateReadinessDisplay,
    renderPlanPreview: renderPlanPreview,
    renderLoadingState: renderLoadingState,
    renderErrorState: renderErrorState,
    SAMPLE_DATA: SAMPLE_DATA,
    readCsrfCookie: readCsrfCookie,
    postAction: postAction,
    submitJsonDossier: submitJsonDossier,
    fetchAccessibleAccounts: fetchAccessibleAccounts,
    populateMcmaAccountSelect: populateMcmaAccountSelect,
    confirmReviewCompleted: confirmReviewCompleted,
    reportProblem: reportProblem,
    parseDossierFileText: parseDossierFileText,
    readDossierFile: readDossierFile,
    renderKpis: renderKpis,
    renderCategoryTabs: renderCategoryTabs,
    renderClaimsTable: renderClaimsTable,
    renderAccountBar: renderAccountBar,
    claimMatchesSearch: claimMatchesSearch,
    ACTION_FILTERS: ACTION_FILTERS,
  };
})();
