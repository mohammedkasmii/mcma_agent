/**
 * MCMA Notification Hub — Interactive JavaScript Controller with Employee Action Tracking
 */

// Default Sample Data (from script spy)
const SAMPLE_NOTIFICATIONS = {
    "timestamp": "2026-08-28 16:45:00",
    "total_categories": 2,
    "total_alerts": 12,
    "categories": [
        {
            "category_name": "MISSIONS (FACTURES REÇUES)",
            "code_alerte": "67D9A055-75D1-47CF-A94E-70F4245DE751",
            "count": 10,
            "items": [
                {
                    "reference": "3.X5.02.2025.01489",
                    "id_sinistre": "701886",
                    "date_survenance": "19/06/2025 00:00",
                    "societaire": "CHAABI LLD",
                    "police": "100170027",
                    "matricule": "85502-E-06",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/701886/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00060",
                    "id_sinistre": "769672",
                    "date_survenance": "07/03/2026 14:20",
                    "societaire": "ERRAZZOUKI AZEDDINE",
                    "police": "320B20100624",
                    "matricule": "62259-A-50",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/769672/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00092",
                    "id_sinistre": "778947",
                    "date_survenance": "04/04/2026 17:30",
                    "societaire": "DAOUDI AISSA",
                    "police": "302503311",
                    "matricule": "53577-A-50",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/778947/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00183",
                    "id_sinistre": "801881",
                    "date_survenance": "22/06/2026 17:00",
                    "societaire": "EL OUAKILI MIMOUNE",
                    "police": "320B23100754",
                    "matricule": "67096-A-20",
                    "nature": "MATÉRIEL",
                    "statut": "EN COURS",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/801881/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00189",
                    "id_sinistre": "802982",
                    "date_survenance": "24/06/2026 19:00",
                    "societaire": "EL AISSATI MOHAMMED",
                    "police": "320B26100288",
                    "matricule": "71617-A-40",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/802982/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00202",
                    "id_sinistre": "805392",
                    "date_survenance": "02/07/2026 16:33",
                    "societaire": "STE BOUYZAOURAN TRANS SARL",
                    "police": "320B22101024",
                    "matricule": "24899-B-40",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/805392/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00219",
                    "id_sinistre": "809727",
                    "date_survenance": "17/07/2026 10:00",
                    "societaire": "BAKHTAOUI IMANE",
                    "police": "320B26100316",
                    "matricule": "WW869667",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/809727/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00221",
                    "id_sinistre": "810152",
                    "date_survenance": "20/07/2026 13:15",
                    "societaire": "EL-BAKKALI YASSINE",
                    "police": "320B23100874",
                    "matricule": "14319-B-50",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/810152/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.13.02.2026.00032",
                    "id_sinistre": "810692",
                    "date_survenance": "21/07/2026 12:15",
                    "societaire": "FATIMA EZZAHRA BENSBAHOU",
                    "police": "313B26100020",
                    "matricule": "52777-E-06",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/810692/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.20.02.2026.00228",
                    "id_sinistre": "811940",
                    "date_survenance": "25/07/2026 20:10",
                    "societaire": "EL MESSAOUDI MIMOUN",
                    "police": "320B23100837",
                    "matricule": "87220-A-50",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/811940/rubrique/gestionexpert-index"
                }
            ]
        },
        {
            "category_name": "RELANCES REÇUES (EXPERT)",
            "code_alerte": "1B03D4D6-6A29-4C93-955E-EF97663862A2",
            "count": 2,
            "items": [
                {
                    "reference": "3.AK.02.2026.00025",
                    "id_sinistre": "815201",
                    "date_survenance": "27/07/2026 11:30",
                    "societaire": "ASAKI EL HOUCINE",
                    "police": "310B25100912",
                    "matricule": "04612-B-48",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/815201/rubrique/gestionexpert-index"
                },
                {
                    "reference": "3.AK.02.2026.00037",
                    "id_sinistre": "815209",
                    "date_survenance": "28/07/2026 09:15",
                    "societaire": "SETTI BILAL",
                    "police": "310B24100155",
                    "matricule": "12324-A-52",
                    "nature": "MATÉRIEL",
                    "statut": "DÉCLARÉ",
                    "direct_url": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/815209/rubrique/gestionexpert-index"
                }
            ]
        }
    ]
};

// Global State
let currentData = SAMPLE_NOTIFICATIONS;
let activeCategory = 'ALL';
let currentSearchQuery = '';
let currentActionFilter = 'ALL'; // 'ALL', 'TODO', 'IN_PROGRESS', 'DONE'
let employeeActions = {}; // { reference: { status: 'TODO'|'IN_PROGRESS'|'DONE'|'WAITING', note: '...', updated_at: '...' } }
let currentEditingRef = null;

// DOM Elements
const kpiTotal = document.getElementById('kpiTotal');
const kpiDone = document.getElementById('kpiDone');
const kpiProgressPct = document.getElementById('kpiProgressPct');
const kpiTodo = document.getElementById('kpiTodo');
const kpiCategories = document.getElementById('kpiCategories');
const categoryTabs = document.getElementById('categoryTabs');
const tableBody = document.getElementById('tableBody');
const searchInput = document.getElementById('searchInput');
const btnClearSearch = document.getElementById('btnClearSearch');
const emptyState = document.getElementById('emptyState');
const btnRefreshLive = document.getElementById('btnRefreshLive');
const btnUploadFile = document.getElementById('btnUploadFile');
const fileInput = document.getElementById('fileInput');
const syncText = document.getElementById('syncText');
const toastContainer = document.getElementById('toastContainer');

// Modal Elements
const noteModal = document.getElementById('noteModal');
const modalClaimRef = document.getElementById('modalClaimRef');
const modalStatusSelect = document.getElementById('modalStatusSelect');
const modalNoteText = document.getElementById('modalNoteText');
const btnCloseModal = document.getElementById('btnCloseModal');
const btnCancelNote = document.getElementById('btnCancelNote');
const btnSaveNote = document.getElementById('btnSaveNote');

// Initialize on Load
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

async function initApp() {
    loadLocalActions();
    setupEventListeners();
    renderAll();

    // 1. Fetch saved actions from backend
    try {
        const actResp = await fetch('/api/v1/notification-actions');
        if (actResp.ok) {
            const actData = await actResp.json();
            if (actData.actions) {
                employeeActions = { ...employeeActions, ...actData.actions };
                saveLocalActions();
                renderAll();
            }
        }
    } catch (e) {}

    // 2. Auto-load latest real extracted notifications instantly
    try {
        const resp = await fetch('/api/v1/cached-notifications');
        if (resp.ok) {
            const data = await resp.json();
            if (data.status === 'success' && data.data && data.data.categories) {
                currentData = data.data;
                activeCategory = 'ALL';
                renderAll();
                syncText.textContent = "Synchronisé (Cache)";
            }
        }
    } catch (e) {}
}

function loadLocalActions() {
    try {
        const stored = localStorage.getItem('mcma_employee_actions');
        if (stored) {
            employeeActions = JSON.parse(stored);
        }
    } catch (e) {}
}

function saveLocalActions() {
    try {
        localStorage.setItem('mcma_employee_actions', JSON.stringify(employeeActions));
    } catch (e) {}
}

function setupEventListeners() {
    // Search input
    searchInput.addEventListener('input', (e) => {
        currentSearchQuery = e.target.value.trim().toLowerCase();
        btnClearSearch.style.display = currentSearchQuery ? 'block' : 'none';
        renderTable();
    });

    btnClearSearch.addEventListener('click', () => {
        searchInput.value = '';
        currentSearchQuery = '';
        btnClearSearch.style.display = 'none';
        renderTable();
    });

    // Action filter pills
    document.querySelectorAll('.filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentActionFilter = pill.dataset.actionFilter;
            renderTable();
        });
    });

    // File Upload (JSON)
    btnUploadFile.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileUpload);

    // Live Refresh
    btnRefreshLive.addEventListener('click', handleLiveRefresh);

    // Modal Events
    btnCloseModal.addEventListener('click', closeModal);
    btnCancelNote.addEventListener('click', closeModal);
    btnSaveNote.addEventListener('click', saveModalNote);
    noteModal.addEventListener('click', (e) => {
        if (e.target === noteModal) closeModal();
    });
}

function renderAll() {
    renderKPIs();
    renderCategoryTabs();
    renderTable();
}

function renderKPIs() {
    const allItems = getAllItems(true); // all across all categories
    const totalAlerts = allItems.length;

    let doneCount = 0;
    allItems.forEach(item => {
        const action = employeeActions[item.reference] || {};
        if (action.status === 'DONE') {
            doneCount++;
        }
    });

    const todoCount = totalAlerts - doneCount;
    const pct = totalAlerts > 0 ? Math.round((doneCount / totalAlerts) * 100) : 0;

    kpiTotal.textContent = totalAlerts;
    kpiDone.innerHTML = `${doneCount} <span class="metric-sub" id="kpiProgressPct">(${pct}%)</span>`;
    kpiTodo.textContent = todoCount;
    kpiCategories.textContent = (currentData.categories || []).length;
}

function renderCategoryTabs() {
    const totalCount = (currentData.categories || []).reduce((sum, c) => sum + (c.items ? c.items.length : 0), 0);

    let html = `
        <button class="tab-btn ${activeCategory === 'ALL' ? 'active' : ''}" data-category="ALL">
            Toutes les alertes <span class="tab-badge">${totalCount}</span>
        </button>
    `;

    (currentData.categories || []).forEach(cat => {
        const count = cat.items ? cat.items.length : 0;
        const isActive = activeCategory === cat.code_alerte;
        html += `
            <button class="tab-btn ${isActive ? 'active' : ''}" data-category="${cat.code_alerte}">
                ${cat.category_name} <span class="tab-badge">${count}</span>
            </button>
        `;
    });

    categoryTabs.innerHTML = html;

    // Attach tab click listeners
    categoryTabs.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            activeCategory = btn.dataset.category;
            renderCategoryTabs();
            renderTable();
        });
    });
}

function getAllItems(ignoreCategoryFilter = false) {
    let all = [];
    (currentData.categories || []).forEach(cat => {
        if (ignoreCategoryFilter || activeCategory === 'ALL' || activeCategory === cat.code_alerte) {
            (cat.items || []).forEach(item => {
                all.push({
                    ...item,
                    category_name: cat.category_name
                });
            });
        }
    });
    return all;
}

function renderTable() {
    const allItems = getAllItems(false);

    // Filter by search query and action status
    const filtered = allItems.filter(item => {
        const action = employeeActions[item.reference] || { status: 'TODO', note: '' };
        const status = action.status || 'TODO';

        // Action Filter
        if (currentActionFilter !== 'ALL') {
            if (currentActionFilter === 'TODO' && status !== 'TODO') return false;
            if (currentActionFilter === 'IN_PROGRESS' && status !== 'IN_PROGRESS') return false;
            if (currentActionFilter === 'DONE' && status !== 'DONE') return false;
        }

        // Search Filter
        if (!currentSearchQuery) return true;
        const haystack = [
            item.reference,
            item.matricule,
            item.societaire,
            item.police,
            item.nature,
            item.statut,
            item.date_survenance,
            action.note || ''
        ].join(' ').toLowerCase();
        return haystack.includes(currentSearchQuery);
    });

    if (filtered.length === 0) {
        tableBody.innerHTML = '';
        emptyState.style.display = 'flex';
        return;
    }

    emptyState.style.display = 'none';

    tableBody.innerHTML = filtered.map(row => {
        const action = employeeActions[row.reference] || { status: 'TODO', note: '' };
        const actStatus = action.status || 'TODO';
        const isDone = actStatus === 'DONE';
        const hasNote = Boolean(action.note && action.note.trim());
        const statusClass = getStatusClass(row.statut);
        const directHref = row.direct_url.startsWith('http') 
            ? row.direct_url 
            : `https://sinauto.mamda-mcma.ma${row.direct_url}`;

        const pillLabel = getActionPillLabel(actStatus);
        const pillClass = getActionPillClass(actStatus);

        return `
            <tr class="${isDone ? 'row-done' : ''}">
                <td>
                    <div class="employee-action-cell">
                        <span class="action-status-pill ${pillClass}" onclick="cycleActionStatus('${row.reference}')" title="Cliquer pour changer de statut">
                            ${pillLabel}
                        </span>
                        <button class="btn-note ${hasNote ? 'has-note' : ''}" onclick="openNoteModal('${row.reference}')" title="${hasNote ? 'Note : ' + action.note : 'Ajouter une note'}">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M12 20h9"></path>
                                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                            </svg>
                            ${hasNote ? 'Note' : ''}
                        </button>
                    </div>
                </td>
                <td>
                    <span class="ref-badge">
                        ${row.reference || 'N/A'}
                        <svg class="copy-icon" onclick="copyToClipboard('${row.reference}')" title="Copier" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                    </span>
                </td>
                <td style="color: var(--text-secondary); font-size: 0.8rem;">
                    ${row.date_survenance || 'N/A'}
                </td>
                <td style="font-weight: 600;">
                    ${row.societaire || 'N/A'}
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-muted); font-size: 0.8rem;">
                    ${row.police || 'N/A'}
                </td>
                <td>
                    <span class="plate-badge">${row.matricule || 'N/A'}</span>
                </td>
                <td>
                    <span class="nature-badge">${row.nature || 'MATÉRIEL'}</span>
                </td>
                <td>
                    <span class="status-badge ${statusClass}">${row.statut || 'DÉCLARÉ'}</span>
                </td>
                <td class="text-right">
                    <a href="${directHref}" target="_blank" rel="noopener noreferrer" class="action-link" title="Ouvrir directement dans MCMA">
                        <span>Ouvrir</span>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                    </a>
                </td>
            </tr>
        `;
    }).join('');
}

function getActionPillLabel(status) {
    switch (status) {
        case 'DONE': return '🟢 Traité';
        case 'IN_PROGRESS': return '🔵 En Cours';
        case 'WAITING': return '🟡 En Attente';
        default: return '⚪ À Traiter';
    }
}

function getActionPillClass(status) {
    switch (status) {
        case 'DONE': return 'action-pill-done';
        case 'IN_PROGRESS': return 'action-pill-inprogress';
        case 'WAITING': return 'action-pill-waiting';
        default: return 'action-pill-todo';
    }
}

function cycleActionStatus(ref) {
    if (!ref) return;
    const current = employeeActions[ref] || { status: 'TODO', note: '' };
    const order = ['TODO', 'IN_PROGRESS', 'DONE', 'WAITING'];
    const nextIdx = (order.indexOf(current.status || 'TODO') + 1) % order.length;
    const nextStatus = order[nextIdx];

    updateAction(ref, nextStatus, current.note || '');
}

async function updateAction(ref, status, note = '') {
    employeeActions[ref] = {
        status: status,
        note: note,
        updated_at: new Date().toLocaleString('fr-FR')
    };

    saveLocalActions();
    renderAll();

    // Sync with backend API
    try {
        await fetch('/api/v1/notification-actions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reference: ref, status: status, note: note })
        });
    } catch (e) {}

    const label = getActionPillLabel(status);
    showToast(`${ref} → ${label}`);
}

function openNoteModal(ref) {
    currentEditingRef = ref;
    const action = employeeActions[ref] || { status: 'TODO', note: '' };

    modalClaimRef.textContent = `Sinistre Référence : ${ref}`;
    modalStatusSelect.value = action.status || 'TODO';
    modalNoteText.value = action.note || '';

    noteModal.classList.add('active');
    modalNoteText.focus();
}

function closeModal() {
    noteModal.classList.remove('active');
    currentEditingRef = null;
}

function saveModalNote() {
    if (!currentEditingRef) return;
    const newStatus = modalStatusSelect.value;
    const newNote = modalNoteText.value.trim();

    updateAction(currentEditingRef, newStatus, newNote);
    closeModal();
}

function getStatusClass(statut) {
    if (!statut) return 'status-declared';
    const s = statut.toUpperCase();
    if (s.includes('DÉCLARÉ') || s.includes('DECLARE')) return 'status-declared';
    if (s.includes('EN COURS') || s.includes('COURS')) return 'status-inprogress';
    if (s.includes('CLÔTURÉ') || s.includes('FERMÉ')) return 'status-closed';
    if (s.includes('RÉOUVERT')) return 'status-reopened';
    return 'status-declared';
}

function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
        try {
            const json = JSON.parse(event.target.result);
            if (json.categories) {
                currentData = json;
                activeCategory = 'ALL';
                renderAll();
                showToast(`Fichier "${file.name}" chargé (${json.total_alerts || 0} alertes)`);
            } else {
                showToast("Format JSON invalide (clé 'categories' manquante).", "error");
            }
        } catch (err) {
            showToast("Erreur de lecture du fichier JSON.", "error");
        }
    };
    reader.readAsText(file);
}

async function handleLiveRefresh() {
    const icon = btnRefreshLive.querySelector('.refresh-icon');
    icon.classList.add('spinning');
    syncText.textContent = "Actualisation...";

    try {
        const resp = await fetch('/api/v1/notifications');
        if (resp.ok) {
            const data = await resp.json();
            if (data.data) {
                currentData = data.data;
                activeCategory = 'ALL';
                renderAll();
                showToast(`Actualisé avec succès depuis MCMA (${currentData.total_alerts} alertes).`);
            }
        } else {
            showToast("Serveur API MCMA non démarré ou session expirée. Affichage des données locales.", "info");
        }
    } catch (e) {
        showToast("Serveur local non connecté. Données de démonstration actives.", "info");
    } finally {
        icon.classList.remove('spinning');
        syncText.textContent = "Prêt";
    }
}

function copyToClipboard(text) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        showToast(`Copié : ${text}`);
    });
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${type === 'error' ? '#ef4444' : '#10b981'}" stroke-width="2">
            ${type === 'error' 
                ? '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>' 
                : '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>'
            }
        </svg>
        <span>${message}</span>
    `;
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 2800);
}
