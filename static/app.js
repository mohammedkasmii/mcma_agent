/**
 * MCMA Notification Hub — dashboard controller.
 *
 * State lives in SQLite on the server, not in this browser. We poll
 * GET /api/v1/state?since=<version> every 15 seconds and merge the delta, so
 * every employee sees the same claims and the same notes (BLUEPRINT §9.1).
 *
 * localStorage holds exactly one thing: the employee's own name, used to
 * attribute their changes. It is never the source of truth for claim data.
 */

const POLL_INTERVAL_MS = 15000;
const NAME_KEY = 'mcma_employee_name';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let claims = new Map();          // claim_id -> claim row (server-owned)
let accounts = [];
let windowStatus = { open: false };
let stateVersion = 0;
let employeeName = '';
let activeAccount = 'ALL';
let activeCategory = 'ALL';
let currentActionFilter = 'ALL';
let currentSearchQuery = '';
let currentEditingId = null;
let pollTimer = null;

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const kpiTotal = $('kpiTotal');
const kpiDone = $('kpiDone');
const kpiTodo = $('kpiTodo');
const kpiCategories = $('kpiCategories');
const categoryTabs = $('categoryTabs');
const accountGrid = $('accountGrid');
const tableBody = $('tableBody');
const searchInput = $('searchInput');
const btnClearSearch = $('btnClearSearch');
const emptyState = $('emptyState');
const btnRefreshLive = $('btnRefreshLive');
const btnWhoAmI = $('btnWhoAmI');
const whoAmILabel = $('whoAmILabel');
const windowBanner = $('windowBanner');
const windowBannerText = $('windowBannerText');
const btnUploadFile = $('btnUploadFile');
const fileInput = $('fileInput');
const syncText = $('syncText');
const toastContainer = $('toastContainer');
const noteModal = $('noteModal');
const modalClaimRef = $('modalClaimRef');
const modalStatusSelect = $('modalStatusSelect');
const modalNoteText = $('modalNoteText');
const btnCloseModal = $('btnCloseModal');
const btnCancelNote = $('btnCancelNote');
const btnSaveNote = $('btnSaveNote');

document.addEventListener('DOMContentLoaded', initApp);

async function initApp() {
    loadEmployeeName();
    setupEventListeners();
    await fetchState(true);
    await fetchAccounts();
    startPolling();
}

// ---------------------------------------------------------------------------
// Identity — attribution, not authentication (§9.2)
// ---------------------------------------------------------------------------

function loadEmployeeName() {
    try { employeeName = localStorage.getItem(NAME_KEY) || ''; } catch (e) { employeeName = ''; }
    renderWhoAmI();
    if (!employeeName) setTimeout(promptForName, 600);
}

function renderWhoAmI() {
    if (whoAmILabel) whoAmILabel.textContent = employeeName || 'Identifiez-vous';
}

function promptForName() {
    const name = window.prompt(
        "Qui etes-vous ?\n\nVotre nom est enregistre sur ce poste et accompagne chaque\nchangement de statut, pour savoir qui a traite quoi.",
        employeeName || ''
    );
    if (name && name.trim()) {
        employeeName = name.trim();
        try { localStorage.setItem(NAME_KEY, employeeName); } catch (e) {}
        renderWhoAmI();
        showToast('Bonjour ' + employeeName);
    }
}

// ---------------------------------------------------------------------------
// Server state
// ---------------------------------------------------------------------------

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => { fetchState(false); fetchAccounts(); }, POLL_INTERVAL_MS);
}

async function fetchState(full) {
    try {
        const since = full ? 0 : stateVersion;
        const resp = await fetch('/api/v1/state?since=' + since);
        if (!resp.ok) throw new Error(resp.status);
        const data = await resp.json();

        (data.claims || []).forEach(c => claims.set(c.id, c));
        (data.archived || []).forEach(id => claims.delete(id));

        stateVersion = data.version || 0;
        windowStatus = data.window || windowStatus;
        accounts = data.accounts || accounts;

        renderAll();
        setSync(windowStatus.open ? 'Synchronise' : 'Portail ferme');
    } catch (e) {
        setSync('Hors ligne');
    }
}

async function fetchAccounts() {
    try {
        const resp = await fetch('/api/v1/accounts');
        if (!resp.ok) return;
        const data = await resp.json();
        accounts = data.accounts || [];
        windowStatus = data.window || windowStatus;
        renderAccounts();
        renderWindowBanner();
    } catch (e) {}
}

function setSync(text) { if (syncText) syncText.textContent = text; }

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderAll() {
    renderWindowBanner();
    renderAccounts();
    renderKPIs();
    renderCategoryTabs();
    renderTable();
}

function renderWindowBanner() {
    if (!windowBanner) return;
    if (windowStatus.open) { windowBanner.style.display = 'none'; return; }
    windowBanner.style.display = 'flex';
    windowBannerText.textContent =
        (windowStatus.message || 'Portail MAMDA/MCMA ferme.') +
        ' Les alertes affichees datent de la derniere synchronisation. Reprise a ' +
        (windowStatus.opens_at || '07:45') + '.';
}

function renderAccounts() {
    if (!accountGrid) return;
    accountGrid.innerHTML = accounts.map(acc => {
        const health = acc.health_status || 'NEVER_AUTHENTICATED';
        const cls = health === 'HEALTHY' ? 'acc-ok'
                  : health === 'EXPIRED' ? 'acc-expired' : 'acc-none';
        const label = health === 'HEALTHY' ? 'Session active'
                    : health === 'EXPIRED' ? 'Session expiree'
                    : health === 'UNKNOWN' ? 'Etat inconnu' : 'Jamais connecte';
        const last = acc.last_successful_poll_at
            ? 'Derniere synchro : ' + formatStamp(acc.last_successful_poll_at)
            : 'Jamais synchronise';
        const stale = isStale(acc.last_successful_poll_at) && health === 'HEALTHY';
        return '' +
            '<div class="account-card ' + cls + ' ' + (stale ? 'acc-stale' : '') + '">' +
                '<div class="account-head">' +
                    '<span class="account-dot"></span>' +
                    '<strong>' + escapeHtml(acc.display_name || acc.account_id) + '</strong>' +
                '</div>' +
                '<div class="account-meta">' + label + (stale ? ' &mdash; donnees anciennes' : '') + '</div>' +
                '<div class="account-meta account-muted">' + last + '</div>' +
                '<div class="account-foot">' +
                    '<span class="account-count">' + (acc.active_claims || 0) + ' alerte(s)</span>' +
                    '<button class="btn-reconnect" onclick="loginAccount(\'' + acc.account_id + '\')" ' +
                        (acc.login_in_flight ? 'disabled' : '') + '>' +
                        (acc.login_in_flight ? 'Connexion...' : 'Reconnecter') +
                    '</button>' +
                '</div>' +
            '</div>';
    }).join('');
}

function isStale(iso) {
    if (!iso) return true;
    const age = (Date.now() - new Date(iso).getTime()) / 60000;
    return age > 20;
}

function formatStamp(iso) {
    try {
        return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return iso; }
}

function visibleClaims() {
    return Array.from(claims.values()).filter(c => {
        if (activeAccount !== 'ALL' && c.account_id !== activeAccount) return false;
        if (activeCategory !== 'ALL' && c.category_code !== activeCategory) return false;
        return true;
    });
}

function renderKPIs() {
    const rows = visibleClaims();
    const done = rows.filter(c => c.employee_status === 'DONE').length;
    const pct = rows.length ? Math.round((done / rows.length) * 100) : 0;
    if (kpiTotal) kpiTotal.textContent = rows.length;
    if (kpiDone) kpiDone.innerHTML = done + ' <span class="metric-sub">(' + pct + '%)</span>';
    if (kpiTodo) kpiTodo.textContent = rows.length - done;
    if (kpiCategories) kpiCategories.textContent = new Set(rows.map(c => c.category_code)).size;
}

function renderCategoryTabs() {
    if (!categoryTabs) return;
    const scoped = Array.from(claims.values())
        .filter(c => activeAccount === 'ALL' || c.account_id === activeAccount);
    const cats = new Map();
    scoped.forEach(c => {
        const prev = cats.get(c.category_code);
        cats.set(c.category_code, { name: c.category_name, count: (prev ? prev.count : 0) + 1 });
    });

    let html = '<button class="tab-btn ' + (activeCategory === 'ALL' ? 'active' : '') +
               '" data-category="ALL">Toutes les alertes ' +
               '<span class="tab-badge">' + scoped.length + '</span></button>';
    cats.forEach((v, code) => {
        html += '<button class="tab-btn ' + (activeCategory === code ? 'active' : '') +
                '" data-category="' + code + '">' + escapeHtml(v.name) +
                ' <span class="tab-badge">' + v.count + '</span></button>';
    });
    categoryTabs.innerHTML = html;
    categoryTabs.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            activeCategory = btn.dataset.category;
            renderCategoryTabs(); renderKPIs(); renderTable();
        });
    });
}

function renderTable() {
    if (!tableBody) return;
    const q = currentSearchQuery;
    const rows = visibleClaims().filter(c => {
        const status = c.employee_status || 'TODO';
        if (currentActionFilter !== 'ALL' && status !== currentActionFilter) return false;
        if (!q) return true;
        return [c.reference, c.matricule, c.societaire, c.police, c.nature,
                c.portal_status, c.date_survenance_raw, c.note || '']
            .join(' ').toLowerCase().indexOf(q) !== -1;
    });

    if (!rows.length) {
        tableBody.innerHTML = '';
        if (emptyState) emptyState.style.display = 'flex';
        return;
    }
    if (emptyState) emptyState.style.display = 'none';

    tableBody.innerHTML = rows.map(row => {
        const status = row.employee_status || 'TODO';
        const isDone = status === 'DONE';
        const hasNote = Boolean(row.note && row.note.trim());
        const pending = row.portal_presence === 'MISSING_PENDING_CONFIRMATION';
        const url = row.direct_url || '';
        const href = url.indexOf('http') === 0 ? url : 'https://sinauto.mamda-mcma.ma' + url;
        const by = row.updated_by ? ' - ' + escapeHtml(row.updated_by) : '';

        return '' +
        '<tr class="' + (isDone ? 'row-done' : '') + ' ' + (pending ? 'row-pending' : '') + '">' +
            '<td><div class="employee-action-cell">' +
                '<span class="action-status-pill ' + pillClass(status) + '" ' +
                      'onclick="cycleActionStatus(' + row.id + ')" ' +
                      'title="Cliquer pour changer' + by + '">' + pillLabel(status) + '</span>' +
                '<button class="btn-note ' + (hasNote ? 'has-note' : '') + '" ' +
                        'onclick="openNoteModal(' + row.id + ')" ' +
                        'title="' + (hasNote ? escapeHtml(row.note) : 'Ajouter une note') + '">' +
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                        '<path d="M12 20h9"></path>' +
                        '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>' +
                    '</svg>' + (hasNote ? 'Note' : '') +
                '</button>' +
            '</div></td>' +
            '<td><span class="ref-badge">' + escapeHtml(row.reference || 'N/A') +
                '<svg class="copy-icon" onclick="copyToClipboard(\'' + escapeAttr(row.reference) + '\')" title="Copier" ' +
                     'width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>' +
                    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
                '</svg></span>' +
                (pending ? '<span class="pending-flag" title="Absente du portail lors de la derniere synchro">&#9888;</span>' : '') +
            '</td>' +
            '<td style="color: var(--text-secondary); font-size: 0.8rem;">' + escapeHtml(row.date_survenance_raw || '') + '</td>' +
            '<td style="font-weight: 600;">' + escapeHtml(row.societaire || 'N/A') + '</td>' +
            '<td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 0.8rem;">' + escapeHtml(row.police || '') + '</td>' +
            '<td><span class="plate-badge">' + escapeHtml(row.matricule || 'N/A') + '</span></td>' +
            '<td><span class="nature-badge">' + escapeHtml(row.nature || 'MATERIEL') + '</span></td>' +
            '<td><span class="status-badge ' + statusClass(row.portal_status) + '">' + escapeHtml(row.portal_status || 'DECLARE') + '</span></td>' +
            '<td class="text-right">' +
                '<a href="' + href + '" target="_blank" rel="noopener noreferrer" class="action-link">' +
                    '<span>Ouvrir</span>' +
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>' +
                        '<polyline points="15 3 21 3 21 9"></polyline>' +
                        '<line x1="10" y1="14" x2="21" y2="3"></line>' +
                    '</svg>' +
                '</a>' +
            '</td>' +
        '</tr>';
    }).join('');
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function cycleActionStatus(claimId) {
    const claim = claims.get(claimId);
    if (!claim) return;
    const order = ['TODO', 'IN_PROGRESS', 'DONE', 'WAITING'];
    const next = order[(order.indexOf(claim.employee_status || 'TODO') + 1) % order.length];
    await updateAction(claimId, next, claim.note || '');
}

async function updateAction(claimId, status, note) {
    if (!employeeName) { promptForName(); if (!employeeName) return; }

    const claim = claims.get(claimId);
    if (claim) {                       // optimistic; the next poll confirms it
        claim.employee_status = status;
        claim.note = note;
        claim.updated_by = employeeName;
        renderKPIs(); renderTable();
    }
    try {
        const resp = await fetch('/api/v1/employee-actions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ claim_id: claimId, status: status, note: note, updated_by: employeeName })
        });
        if (!resp.ok) throw new Error(resp.status);
        showToast((claim ? claim.reference : '') + ' -> ' + pillLabel(status));
        fetchState(false);
    } catch (e) {
        showToast("Echec de l'enregistrement - verifiez le serveur.", 'error');
        fetchState(true);
    }
}

async function loginAccount(accountId) {
    showToast('Ouverture de la fenetre de connexion sur le PC serveur...');
    try {
        const resp = await fetch('/api/v1/accounts/' + accountId + '/login', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) { showToast(data.detail || 'Connexion refusee.', 'error'); return; }
        showToast(data.message || 'Connexion terminee.', data.status === 'success' ? 'success' : 'error');
        fetchAccounts();
    } catch (e) {
        showToast('Impossible de lancer la connexion.', 'error');
    }
}

async function handleRefresh() {
    const icon = btnRefreshLive ? btnRefreshLive.querySelector('.refresh-icon') : null;
    if (icon) icon.classList.add('spinning');
    setSync('Actualisation...');
    try {
        const resp = await fetch('/api/v1/refresh', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) { showToast(data.detail || 'Actualisation impossible.', 'error'); return; }
        await fetchState(false);
        await fetchAccounts();
        showToast('Actualise depuis le portail.');
    } catch (e) {
        showToast('Serveur injoignable.', 'error');
    } finally {
        if (icon) icon.classList.remove('spinning');
        setSync(windowStatus.open ? 'Synchronise' : 'Portail ferme');
    }
}

// ---------------------------------------------------------------------------
// Modal, helpers, events
// ---------------------------------------------------------------------------

function openNoteModal(claimId) {
    const claim = claims.get(claimId);
    if (!claim) return;
    currentEditingId = claimId;
    modalClaimRef.textContent = 'Sinistre Reference : ' + claim.reference;
    modalStatusSelect.value = claim.employee_status || 'TODO';
    modalNoteText.value = claim.note || '';
    noteModal.classList.add('active');
    modalNoteText.focus();
}

function closeModal() { noteModal.classList.remove('active'); currentEditingId = null; }

function saveModalNote() {
    if (currentEditingId === null) return;
    updateAction(currentEditingId, modalStatusSelect.value, modalNoteText.value.trim());
    closeModal();
}

function pillLabel(s) {
    return s === 'DONE' ? '\u{1F7E2} Traite'
         : s === 'IN_PROGRESS' ? '\u{1F535} En Cours'
         : s === 'WAITING' ? '\u{1F7E1} En Attente' : '\u26AA A Traiter';
}

function pillClass(s) {
    return s === 'DONE' ? 'action-pill-done'
         : s === 'IN_PROGRESS' ? 'action-pill-inprogress'
         : s === 'WAITING' ? 'action-pill-waiting' : 'action-pill-todo';
}

function statusClass(statut) {
    const s = (statut || '').toUpperCase();
    if (s.indexOf('COURS') !== -1) return 'status-inprogress';
    if (s.indexOf('CL') === 0 || s.indexOf('FERM') !== -1) return 'status-closed';
    if (s.indexOf('OUVERT') !== -1) return 'status-reopened';
    return 'status-declared';
}

function escapeHtml(v) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, ch => map[ch]);
}
function escapeAttr(v) {
    return String(v === null || v === undefined ? '' : v).replace(/['\\]/g, '\\$&');
}

function copyToClipboard(text) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => showToast('Copie : ' + text));
}

function showToast(message, type) {
    if (!toastContainer) return;
    type = type || 'success';
    const toast = document.createElement('div');
    toast.className = 'toast';
    const stroke = type === 'error' ? '#ef4444' : '#10b981';
    const glyph = type === 'error'
        ? '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>'
        : '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>';
    toast.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + stroke +
                      '" stroke-width="2">' + glyph + '</svg><span>' + escapeHtml(message) + '</span>';
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 2800);
}

function setupEventListeners() {
    if (searchInput) {
        searchInput.addEventListener('input', e => {
            currentSearchQuery = e.target.value.trim().toLowerCase();
            if (btnClearSearch) btnClearSearch.style.display = currentSearchQuery ? 'block' : 'none';
            renderTable();
        });
    }
    if (btnClearSearch) {
        btnClearSearch.addEventListener('click', () => {
            searchInput.value = ''; currentSearchQuery = '';
            btnClearSearch.style.display = 'none'; renderTable();
        });
    }
    document.querySelectorAll('.filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentActionFilter = pill.dataset.actionFilter;
            renderTable();
        });
    });
    if (btnRefreshLive) btnRefreshLive.addEventListener('click', handleRefresh);
    if (btnWhoAmI) btnWhoAmI.addEventListener('click', promptForName);
    // Superseded by the server-side poller: claims now come from the database.
    if (btnUploadFile) btnUploadFile.style.display = 'none';
    if (btnCloseModal) btnCloseModal.addEventListener('click', closeModal);
    if (btnCancelNote) btnCancelNote.addEventListener('click', closeModal);
    if (btnSaveNote) btnSaveNote.addEventListener('click', saveModalNote);
    if (noteModal) noteModal.addEventListener('click', e => { if (e.target === noteModal) closeModal(); });
}
