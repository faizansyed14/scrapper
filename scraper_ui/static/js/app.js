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

    // Validate URL
    try {
        new URL(url);
    } catch {
        showToast('Please enter a valid URL', 'error');
        urlInput.focus();
        return;
    }

    // Disable button, show spinner
    scrapeBtn.disabled = true;
    scrapeBtnText.textContent = 'Scraping...';
    scrapeBtnSpinner.style.display = 'inline-block';

    // Show loading state in results
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
            }),
        });

        const data = await response.json();

        if (response.ok) {
            currentJobId = data.job_id;
            showToast(`Scraping started (${data.site_type})...`, 'info');
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
            } else if (data.status === 'error') {
                clearInterval(pollInterval);
                pollInterval = null;
                showErrorState(data.message);
                resetScrapeButton();
                showToast('Scraping failed: ' + data.message, 'error');
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
            <p>Scraping in progress...</p>
            <p style="font-size: 12px; color: var(--text-muted)">This may take a moment depending on the number of pages</p>
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

function showResultsToolbar(data) {
    resultToolbar.style.display = 'flex';
    if (isViewingDatabase) {
        document.getElementById('result-count').innerHTML = `Showing <strong>${data.length}</strong> jobs from <strong>Global Database ${currentDbSource ? '('+currentDbSource+')' : '(All Portals)'}</strong>`;
        document.getElementById('delete-db-btn').style.display = 'inline-block';
    } else {
        document.getElementById('result-count').innerHTML = `Showing <strong>${data.results.length}</strong> results from <strong>${data.site_type}</strong>`;
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
        let fetchUrl = `/api/export/${currentJobId}?sort=${sortSelect.value}`;
        if (isViewingDatabase) {
            fetchUrl = currentDbSource ? `/api/database/export?source=${currentDbSource}` : `/api/database/export`;
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
async function loadDbStats() {
    try {
        const response = await fetch('/api/database');
        const data = await response.json();
        statDb.textContent = data.length;
    } catch (error) {
        console.error('Failed to load DB stats', error);
    }
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

async function viewDatabase(source = '') {
    showLoadingState();
    try {
        currentDbSource = source;
        const fetchUrl = source ? `/api/database?source=${source}` : '/api/database';
        const response = await fetch(fetchUrl);
        const data = await response.json();
        
        isViewingDatabase = true;
        currentJobId = 'database';
        allResults = data;
        
        // If no source filter, update global stats
        if (!source) {
            statDb.textContent = data.length;
        }

        // Update DB Tabs Active State
        document.querySelectorAll('.db-tab-btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.textContent.includes(source || 'All Portals')) {
                btn.classList.add('active');
            }
        });

        searchInput.value = '';
        sortSelect.value = 'recent';
        applyFiltersAndSort();
        showResultsToolbar(data);

        // Deselect history items
        document.querySelectorAll('.history-item').forEach(item => {
            item.classList.remove('active');
        });
        
        showToast(source ? `Loaded ${source} Database` : 'Loaded Global Database', 'success');
    } catch (error) {
        showErrorState('Failed to load database');
        showToast('Error loading database', 'error');
    }
}

async function deleteDatabase() {
    const confirmMsg = currentDbSource ? `Are you sure you want to delete ALL ${currentDbSource} jobs from the database?` : `Are you sure you want to completely clear the entire database? This cannot be undone.`;
    
    if (!confirm(confirmMsg)) return;

    try {
        const fetchUrl = currentDbSource ? `/api/database/clear?source=${currentDbSource}` : '/api/database/clear';
        const response = await fetch(fetchUrl, { method: 'DELETE' });
        
        if (response.ok) {
            showToast('Database deleted successfully', 'success');
            loadDbStats();
            viewDatabase(currentDbSource);
        } else {
            showToast('Failed to delete database', 'error');
        }
    } catch (error) {
        showToast('Failed to delete database', 'error');
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
