/**
 * Scrapling UI — Main Application Logic
 */

// ── State ───────────────────────────────────────────────
let currentJobId = null;
let pollInterval = null;
let allResults = [];
let totalJobs = 0;
let totalItems = 0;
let isViewingDatabase = false;
let currentDbSource = '';
let currentDbCountry = '';  // e.g. 'UAE', 'KSA', 'Qatar', 'Kuwait', ''

// ── DOM References ──────────────────────────────────────
const urlInput = document.getElementById('url-input');
const siteSelect = document.getElementById('site-type');
const maxPagesInput = document.getElementById('max-pages');
const scrapeBtn = document.getElementById('scrape-btn');
const scrapeBtnText = document.getElementById('scrape-btn-text');
const scrapeBtnSpinner = document.getElementById('scrape-btn-spinner');
const resultsPanel = document.getElementById('results-panel');
const resultsBody = document.getElementById('results-body');
const resultToolbar = document.getElementById('results-toolbar');
const historyList = document.getElementById('history-list');
const searchInput = document.getElementById('search-filter');
const sortSelect = document.getElementById('sort-select');
const statItems = document.getElementById('stat-items');
const statDb = document.getElementById('stat-db');

// ── Initialize ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    loadDbStats();
    setupEventListeners();
});

function setupEventListeners() {

    // Search filter
    searchInput.addEventListener('input', () => {
        applyFiltersAndSort();
    });

    // Sort select
    sortSelect.addEventListener('change', () => {
        applyFiltersAndSort();
    });

    // Enter key on URL input
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') startScrape();
    });
}

// ── Presets ──────────────────────────────────────────────
function applyPreset(portal) {
    const country = document.getElementById('preset-country').value;

    // Default config mapping
    const configs = {
        'naukrigulf': {
            'uae': 'https://www.naukrigulf.com/jobs-in-uae',
            'ksa': 'https://www.naukrigulf.com/jobs-in-saudi-arabia',
            'qatar': 'https://www.naukrigulf.com/jobs-in-qatar',
            'kuwait': 'https://www.naukrigulf.com/jobs-in-kuwait'
        },
        'linkedin': {
            'uae': 'https://www.linkedin.com/jobs/search/?location=United%20Arab%20Emirates',
            'ksa': 'https://www.linkedin.com/jobs/search/?location=Saudi%20Arabia',
            'qatar': 'https://www.linkedin.com/jobs/search/?location=Qatar',
            'kuwait': 'https://www.linkedin.com/jobs/search/?location=Kuwait'
        },
        'gulftalent': {
            'uae': 'https://www.gulftalent.com/uae/jobs',
            'ksa': 'https://www.gulftalent.com/saudi-arabia/jobs',
            'qatar': 'https://www.gulftalent.com/qatar/jobs',
            'kuwait': 'https://www.gulftalent.com/kuwait/jobs'
        },
        'bayt': {
            'uae': 'https://www.bayt.com/en/uae/jobs/',
            'ksa': 'https://www.bayt.com/en/saudi-arabia/jobs/',
            'qatar': 'https://www.bayt.com/en/qatar/jobs/',
            'kuwait': 'https://www.bayt.com/en/kuwait/jobs/'
        }
    };

    urlInput.value = configs[portal][country];
    setSiteType(portal);
}

// Update preset labels when country changes
document.getElementById('preset-country').addEventListener('change', (e) => {
    const text = e.target.options[e.target.selectedIndex].text;
    const shortText = text.includes('(') ? text.split('(')[1].replace(')', '') : text;
    document.querySelectorAll('.country-label').forEach(el => {
        el.textContent = shortText;
    });
});


function setSiteType(type) {
    siteSelect.value = type;
    // Highlight matching tab
    document.querySelectorAll('.site-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.type === type);
    });
}

function selectSiteTab(type) {
    setSiteType(type);
}

// ── Auto-detect site type from URL ──────────────────────
urlInput.addEventListener('input', () => {
    const url = urlInput.value.toLowerCase();
    if (url.includes('naukrigulf')) {
        setSiteType('naukrigulf');
    } else if (url.includes('linkedin')) {
        setSiteType('linkedin');
    } else if (url.includes('gulftalent')) {
        setSiteType('gulftalent');
    } else if (url.includes('bayt')) {
        setSiteType('bayt');
    } else if (url.length > 10) {
        setSiteType('auto');
    }
});

// ── Start Scraping ──────────────────────────────────────
async function startScrape() {
    const url = urlInput.value.trim();
    if (!url) {
        showToast('Please enter a URL', 'error');
        urlInput.focus();
        return;
    }

    try { new URL(url); } catch {
        showToast('Please enter a valid URL', 'error');
        urlInput.focus();
        return;
    }

    // Read selected country from preset dropdown
    const countryMap = { uae: 'UAE', ksa: 'KSA', qatar: 'Qatar', kuwait: 'Kuwait' };
    const presetCountryVal = document.getElementById('preset-country').value;
    const country = countryMap[presetCountryVal] || '';

    scrapeBtn.disabled = true;
    scrapeBtnText.textContent = 'Scraping...';
    scrapeBtnSpinner.style.display = 'inline-block';
    showLoadingState();
    isViewingDatabase = false;

    try {
        const response = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                max_pages: parseInt(maxPagesInput.value) || 5,
                site_type: siteSelect.value,
                country: country,
            }),
        });

        const data = await response.json();

        if (response.ok) {
            currentJobId = data.job_id;
            showToast(`Scraping started (${data.site_type}${country ? ' · ' + country : ''})...`, 'info');
            startPolling(data.job_id);
        } else {
            showToast(data.error || 'Failed to start scraping', 'error');
            resetScrapeButton();
        }
    } catch (error) {
        showToast('Connection error. Is the server running?', 'error');
        resetScrapeButton();
    }
}

// ── Poll for Results ────────────────────────────────────
function startPolling(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/status/${jobId}`);
            const data = await response.json();

            if (data.status === 'completed') {
                clearInterval(pollInterval);
                pollInterval = null;

                allResults = data.results;
                applyFiltersAndSort();
                showResultsToolbar(data);
                resetScrapeButton();
                loadHistory();

                totalJobs++;
                totalItems += data.results.length;
                updateStats();

                if (data.results.length > 0) {
                    showToast(`Found ${data.results.length} items!`, 'success');
                } else {
                    showToast('No data found. Try a different URL or selector.', 'info');
                }
            } else if (data.status === 'cancelled') {
                clearInterval(pollInterval);
                pollInterval = null;
                showErrorState('Scraping was cancelled by user.');
                resetScrapeButton();
                showToast('Scraping cancelled', 'info');
                loadHistory();
            } else if (data.status === 'error') {
                clearInterval(pollInterval);
                pollInterval = null;
                showErrorState(data.message);
                resetScrapeButton();
                showToast('Scraping failed: ' + data.message, 'error');
            } else if (data.status === 'running') {
                // Update loading message with progress from server
                const msgEl = document.querySelector('.loading-overlay p:first-of-type');
                if (msgEl) msgEl.textContent = data.message || 'Scraping in progress...';
            }
            // else still running - keep polling
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, 1500);
}

// ── Render Results Table ────────────────────────────────
function renderResults(data) {
    if (!data || data.length === 0) {
        showEmptyState();
        return;
    }

    // Defined column order
    const columnOrder = ['title', 'company', 'location', 'experience', 'posted'];

    // Find which keys from our order exist in the data
    const keys = columnOrder.filter(key =>
        data.some(row => row.hasOwnProperty(key))
    );

    let html = `
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width: 50px">#</th>
                        ${keys.map(k => `<th>${escapeHtml(formatHeader(k))}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
    `;

    data.forEach((row, idx) => {
        html += `<tr class="fade-in" style="animation-delay: ${idx * 0.02}s">`;
        html += `<td class="row-number">${idx + 1}</td>`;

        keys.forEach(key => {
            let value = row[key] || '';
            html += `<td title="${escapeHtml(value)}">${escapeHtml(truncate(value, 60))}</td>`;
        });

        html += '</tr>';
    });

    html += '</tbody></table></div>';
    resultsBody.innerHTML = html;
}

// ── Filter & Sort Results ───────────────────────────────
function filterResults(data, query) {
    if (!query) return data;
    const q = query.toLowerCase();
    return data.filter(row =>
        Object.values(row).some(val =>
            String(val).toLowerCase().includes(q)
        )
    );
}

function extractTimeValue(str) {
    if (!str) return Infinity;
    str = String(str).toLowerCase();

    if (str.includes('active') || str.includes('just now')) return 0;

    const match = str.match(/(\d+)\s*(min|hour|hr|day|week|month|year)s?/);
    if (match) {
        let val = parseInt(match[1], 10);
        let unit = match[2];

        if (unit === 'min') return val;
        if (unit === 'hour' || unit === 'hr') return val * 60;
        if (unit === 'day') return val * 24 * 60;
        if (unit === 'week') return val * 7 * 24 * 60;
        if (unit === 'month') return val * 30 * 24 * 60;
        if (unit === 'year') return val * 365 * 24 * 60;
    }

    let parsed = Date.parse(str);
    if (!isNaN(parsed)) {
        return (Date.now() - parsed) / 60000; // in minutes
    }

    return Infinity;
}

function applyFiltersAndSort() {
    let data = filterResults(allResults, searchInput.value);

    // Create a copy of the array before sorting to avoid mutating the original
    data = [...data];

    const sortVal = sortSelect.value;
    if (sortVal === 'recent') {
        data.sort((a, b) => extractTimeValue(a.posted) - extractTimeValue(b.posted));
    } else if (sortVal === 'oldest') {
        data.sort((a, b) => extractTimeValue(b.posted) - extractTimeValue(a.posted));
    }

    renderResults(data);
}

// ── UI States ───────────────────────────────────────────
function showLoadingState() {
    resultToolbar.style.display = 'none';
    resultsBody.innerHTML = `
        <div class="loading-overlay">
            <div class="loading-ring"></div>
            <p>Starting scraper...</p>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 20px;">This may take a moment depending on the number of pages</p>
            <button class="btn btn-danger btn-sm" onclick="cancelScrape()">
                🛑 Cancel Scraping
            </button>
        </div>
    `;
}

async function cancelScrape() {
    if (!currentJobId) return;
    
    showToast('Stopping scraper...', 'info');
    try {
        const response = await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
        if (response.ok) {
            // startPolling will handle the 'cancelled' state
        }
    } catch (error) {
        showToast('Cancel request failed', 'error');
    }
}

function showDbLoadingState() {
    resultToolbar.style.display = 'none';
    resultsBody.innerHTML = `
        <div class="loading-overlay">
            <div class="loading-ring"></div>
            <p>Fetching from database...</p>
        </div>
    `;
}

function showEmptyState() {
    resultToolbar.style.display = 'none';
    resultsBody.innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">🕸️</div>
            <h3>No Data Yet</h3>
            <p>Enter a URL and hit "Start Scraping" to extract data. Results will appear here.</p>
        </div>
    `;
}

function showErrorState(message) {
    resultToolbar.style.display = 'none';
    resultsBody.innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">⚠️</div>
            <h3>Scraping Failed</h3>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

function showResultsToolbar() {
    resultToolbar.style.display = 'flex';
    if (isViewingDatabase) {
        const label = currentDbSource ? currentDbSource : 'All Portals';
        const loaded = allResults.length;
        document.getElementById('result-count').innerHTML =
            `Showing <strong>${loaded.toLocaleString()}</strong> of <strong>${dbTotalCount.toLocaleString()}</strong> jobs — <strong>${label}</strong>`;
        document.getElementById('delete-db-btn').style.display = 'inline-block';
    } else {
        // called with scrape job data object
        const d = arguments[0];
        document.getElementById('result-count').innerHTML =
            `Showing <strong>${d.results.length}</strong> results from <strong>${d.site_type}</strong>`;
        document.getElementById('delete-db-btn').style.display = 'none';
    }
}

function resetScrapeButton() {
    scrapeBtn.disabled = false;
    scrapeBtnText.textContent = 'Start Scraping';
    scrapeBtnSpinner.style.display = 'none';
}

function updateStats() {
    statItems.textContent = totalItems;
}

// ── Export to Excel ─────────────────────────────────────
async function exportExcel() {
    if (!currentJobId) {
        showToast('No data to export', 'error');
        return;
    }

    showToast('Generating Excel file...', 'info');

    try {
        let fetchUrl;
        if (isViewingDatabase) {
            const params = new URLSearchParams();
            if (currentDbSource) params.append('source', currentDbSource);
            if (currentDbCountry) params.append('country', currentDbCountry);
            fetchUrl = `/api/database/export?${params.toString()}`;
        } else {
            fetchUrl = `/api/export/${currentJobId}?sort=${sortSelect.value}`;
        }
        const response = await fetch(fetchUrl);

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = response.headers.get('content-disposition')?.split('filename=')[1] || 'scraped_data.xlsx';
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            showToast('Excel file downloaded!', 'success');
        } else {
            const data = await response.json();
            showToast(data.error || 'Export failed', 'error');
        }
    } catch (error) {
        showToast('Export failed: ' + error.message, 'error');
    }
}

function handleImportExcel() {
    // Open modal instead of triggering hidden input
    document.getElementById('modal-import-country').value = currentDbCountry;
    document.getElementById('modal-import-source').value = currentDbSource || 'Naukrigulf';
    document.getElementById('import-modal').style.display = 'flex';
}

function closeImportModal() {
    document.getElementById('import-modal').style.display = 'none';
}

async function submitModalImport() {
    const fileInput = document.getElementById('modal-import-file');
    const country = document.getElementById('modal-import-country').value;
    const source = document.getElementById('modal-import-source').value;
    const file = fileInput.files[0];

    if (!file) {
        showToast('Please select a file', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('default_source', source);
    formData.append('default_country', country);

    showToast('Importing Excel data...', 'info');
    closeImportModal();

    try {
        const response = await fetch('/api/database/import', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();

        if (response.ok) {
            showToast(`Import Success: ${data.inserted} new jobs added!`, 'success');
            loadDbStats();
            // If the import matches current filters, refresh view
            if (currentDbSource === source || !currentDbSource) {
                viewDatabase(currentDbSource, currentDbCountry);
            }
        } else {
            showToast(data.error || 'Import failed', 'error');
        }
    } catch (error) {
        showToast('Import failed: ' + error.message, 'error');
    } finally {
        fileInput.value = ''; // clear for next use
    }
}

// ── History ─────────────────────────────────────────────
async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const jobs = await response.json();

        if (jobs.length === 0) {
            historyList.innerHTML = `
                <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px;">
                    No previous scrapes yet
                </div>
            `;
            return;
        }

        historyList.innerHTML = jobs.reverse().map(job => `
            <div class="history-item ${job.id === currentJobId ? 'active' : ''}" onclick="viewJob('${job.id}')">
                <div class="history-item-header">
                    <span class="history-item-site ${job.site_type}">${job.site_type}</span>
                    <span class="status-badge ${job.status}">
                        <span class="status-dot"></span>
                        ${job.status}
                    </span>
                </div>
                <div class="history-item-url" title="${escapeHtml(job.url)}">${escapeHtml(job.url)}</div>
                <div class="history-item-meta">
                    <span>📊 ${job.result_count} items</span>
                    <span>🕐 ${job.created_at}</span>
                </div>
                <div class="history-item-actions">
                    <button class="btn btn-icon btn-danger btn-sm" onclick="event.stopPropagation(); deleteJob('${job.id}')" title="Delete">
                        🗑️
                    </button>
                </div>
            </div>
        `).join('');

        // Update stats
        totalJobs = jobs.length;
        totalItems = jobs.reduce((sum, j) => sum + j.result_count, 0);
        updateStats();
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

async function viewJob(jobId) {
    try {
        const response = await fetch(`/api/status/${jobId}`);
        const data = await response.json();

        currentJobId = jobId;
        isViewingDatabase = false;
        allResults = data.results;
        searchInput.value = '';
        sortSelect.value = 'default';
        applyFiltersAndSort();
        showResultsToolbar(data);

        // Update active state in history
        document.querySelectorAll('.history-item').forEach(item => {
            item.classList.remove('active');
        });
        event.currentTarget.classList.add('active');
    } catch (error) {
        showToast('Failed to load job data', 'error');
    }
}

async function deleteJob(jobId) {
    try {
        await fetch(`/api/delete/${jobId}`, { method: 'DELETE' });
        if (jobId === currentJobId) {
            currentJobId = null;
            allResults = [];
            showEmptyState();
            resultToolbar.style.display = 'none';
        }
        loadHistory();
        showToast('Job deleted', 'info');
    } catch (error) {
        showToast('Failed to delete job', 'error');
    }
}

// ── Database ────────────────────────────────────────────
let dbCurrentPage = 1;
let dbHasMore = false;
let dbTotalCount = 0;

async function loadDbStats() {
    try {
        const response = await fetch('/api/database?limit=1');
        const data = await response.json();
        statDb.textContent = data.total.toLocaleString();
    } catch (error) {
        console.error('Failed to load DB stats', error);
    }
}

// 2-level tab selectors
function selectDbCountry(country) {
    currentDbCountry = country;
    document.querySelectorAll('.db-country-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.country === country);
    });
    viewDatabase(currentDbSource, currentDbCountry);
}

function selectDbPortal(source) {
    currentDbSource = source;
    document.querySelectorAll('.db-portal-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.source === source);
    });
    viewDatabase(currentDbSource, currentDbCountry);
}

function showView(view, source = '') {
    // Update nav active states
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

    const dbControls = document.getElementById('db-portal-tabs');
    const topControls = document.getElementById('top-controls');
    const resultsPanelHeader = document.getElementById('results-panel-header');

    if (view === 'database') {
        isViewingDatabase = true;
        currentDbSource = source;
        dbControls.style.display = 'flex';
        if (topControls) topControls.style.display = 'none';
        resultsPanelHeader.style.display = 'none'; // hide the regular header because we have tabs

        // Highlight correct nav link
        document.querySelector('.nav-dropdown .nav-link').classList.add('active');

        viewDatabase(source);
    } else {
        isViewingDatabase = false;
        currentDbSource = '';
        dbControls.style.display = 'none';
        if (topControls) topControls.style.display = 'grid';
        resultsPanelHeader.style.display = 'flex';

        // Highlight nav link
        document.querySelector('.nav-link[onclick="showView(\'scraper\')"]').classList.add('active');

        // If we have a current scrape job, view it, else show empty
        if (currentJobId && currentJobId !== 'database') {
            viewJob(currentJobId);
        } else {
            showEmptyState();
        }
    }
}

async function viewDatabase(source = '', country = '') {
    currentDbSource = source;
    currentDbCountry = country;
    dbCurrentPage = 1;
    dbHasMore = false;
    allResults = [];

    showDbLoadingState();
    try {
        isViewingDatabase = true;
        currentJobId = 'database';

        const url = new URL('/api/database', window.location.origin);
        if (source) url.searchParams.append('source', source);
        if (country) url.searchParams.append('country', country);
        url.searchParams.append('page', 1);
        url.searchParams.append('limit', 100);

        const response = await fetch(url);
        const data = await response.json();

        dbTotalCount = data.total;
        dbHasMore = data.has_more;
        dbCurrentPage = 1;
        allResults = data.jobs;

        statDb.textContent = data.total.toLocaleString();

        // Sync tab active states
        document.querySelectorAll('.db-country-tab').forEach(btn =>
            btn.classList.toggle('active', btn.dataset.country === country));
        document.querySelectorAll('.db-portal-tab').forEach(btn =>
            btn.classList.toggle('active', btn.dataset.source === source));

        searchInput.value = '';
        sortSelect.value = 'default';
        renderResults(allResults);
        appendLoadMoreButton();
        showResultsToolbar();

        document.querySelectorAll('.history-item').forEach(item => item.classList.remove('active'));

        const label = [country, source].filter(Boolean).join(' · ') || 'All';
        showToast(`Loaded ${label} (${data.total.toLocaleString()} jobs)`, 'success');
    } catch (error) {
        showErrorState('Failed to load database');
        showToast('Error loading database', 'error');
    }
}

async function loadMoreDbJobs() {
    if (!dbHasMore) return;
    dbCurrentPage++;

    const btn = document.getElementById('load-more-btn');
    if (btn) btn.textContent = 'Loading...';

    try {
        const url = new URL('/api/database', window.location.origin);
        if (currentDbSource) url.searchParams.append('source', currentDbSource);
        if (currentDbCountry) url.searchParams.append('country', currentDbCountry);
        url.searchParams.append('page', dbCurrentPage);
        url.searchParams.append('limit', 100);

        const response = await fetch(url);
        const data = await response.json();

        dbHasMore = data.has_more;
        allResults = allResults.concat(data.jobs);

        const tbody = resultsBody.querySelector('tbody');
        const startIdx = allResults.length - data.jobs.length;
        const columnOrder = ['title', 'company', 'location', 'experience', 'posted'];
        const keys = columnOrder.filter(k => allResults.some(r => r.hasOwnProperty(k)));

        data.jobs.forEach((row, i) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td class="row-number">${startIdx + i + 1}</td>` +
                keys.map(k => `<td title="${escapeHtml(row[k] || '')}">${escapeHtml(truncate(row[k] || '', 60))}</td>`).join('');
            if (tbody) tbody.appendChild(tr);
        });

        appendLoadMoreButton();
        showResultsToolbar();
    } catch (e) {
        showToast('Failed to load more', 'error');
    }
}

function appendLoadMoreButton() {
    const existing = document.getElementById('load-more-btn');
    if (existing) existing.remove();
    if (!dbHasMore) return;

    const loaded = Math.min(dbCurrentPage * 100, dbTotalCount);
    const btn = document.createElement('button');
    btn.id = 'load-more-btn';
    btn.className = 'btn btn-secondary';
    btn.style = 'margin: 16px auto; display: block; min-width: 200px;';
    btn.textContent = `Load More (${loaded.toLocaleString()} / ${dbTotalCount.toLocaleString()})`;
    btn.onclick = loadMoreDbJobs;
    resultsBody.appendChild(btn);
}

async function deleteDatabase() {
    const parts = [currentDbCountry, currentDbSource].filter(Boolean);
    const label = parts.join(' · ') || 'entire';

    /**
     * WARNING: This will permanently delete all matching jobs from the database.
     * This cannot be undone.
     */
    if (!confirm(`Delete ALL ${label} jobs from database? Cannot be undone.`)) return;

    try {
        const params = new URLSearchParams();
        if (currentDbSource) params.append('source', currentDbSource);
        if (currentDbCountry) params.append('country', currentDbCountry);
        const response = await fetch(`/api/database/clear?${params.toString()}`, { method: 'DELETE' });

        if (response.ok) {
            showToast('Deleted successfully', 'success');
            loadDbStats();
            viewDatabase(currentDbSource, currentDbCountry);
        } else {
            showToast('Failed to delete', 'error');
        }
    } catch (error) {
        showToast('Failed to delete', 'error');
    }
}

// ── Toast Notifications ─────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span> ${escapeHtml(message)}`;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100px)';
        toast.style.transition = 'all 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ── Utilities ───────────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function formatHeader(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
