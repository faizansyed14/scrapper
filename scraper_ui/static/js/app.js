/**
 * Scrapling UI — Main Application Logic
 */

// ── State ───────────────────────────────────────────────
let currentJobId = null;
let pollInterval = null;
let allResults = [];
let totalJobs = 0;
let totalItems = 0;

// ── DOM References ──────────────────────────────────────
const urlInput = document.getElementById('url-input');
const siteSelect = document.getElementById('site-type');
const maxPagesRange = document.getElementById('max-pages');
const maxPagesValue = document.getElementById('max-pages-value');
const scrapeBtn = document.getElementById('scrape-btn');
const scrapeBtnText = document.getElementById('scrape-btn-text');
const scrapeBtnSpinner = document.getElementById('scrape-btn-spinner');
const resultsPanel = document.getElementById('results-panel');
const resultsBody = document.getElementById('results-body');
const resultToolbar = document.getElementById('results-toolbar');
const historyList = document.getElementById('history-list');
const searchInput = document.getElementById('search-filter');
const sortSelect = document.getElementById('sort-select');
const statJobs = document.getElementById('stat-jobs');
const statItems = document.getElementById('stat-items');

// ── Initialize ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    setupEventListeners();
});

function setupEventListeners() {
    // Range slider
    maxPagesRange.addEventListener('input', () => {
        maxPagesValue.textContent = maxPagesRange.value;
    });

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
function setPreset(type) {
    // Remove active class from all preset buttons
    document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    event.currentTarget.classList.add('active');

    switch (type) {
        case 'naukrigulf-jobs':
            urlInput.value = 'https://www.naukrigulf.com/jobs-in-uae';
            setSiteType('naukrigulf');
            break;
        case 'naukrigulf-it':
            urlInput.value = 'https://www.naukrigulf.com/it-jobs-in-uae';
            setSiteType('naukrigulf');
            break;
        case 'linkedin-jobs':
            urlInput.value = 'https://www.linkedin.com/jobs/search/?location=United%20Arab%20Emirates';
            setSiteType('linkedin');
            break;
        case 'linkedin-it':
            urlInput.value = 'https://www.linkedin.com/jobs/search/?keywords=IT&location=United%20Arab%20Emirates';
            setSiteType('linkedin');
            break;
    }
}

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

    try {
        const response = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                max_pages: parseInt(maxPagesRange.value),
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

    // Get all unique keys (excluding internal ones)
    const excludeKeys = ['source', 'page'];
    const keys = [];
    data.forEach(row => {
        Object.keys(row).forEach(key => {
            if (!keys.includes(key) && !excludeKeys.includes(key)) {
                keys.push(key);
            }
        });
    });

    let html = `
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>#</th>
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
            if (key === 'link' && value) {
                html += `<td><a href="${escapeHtml(value)}" target="_blank" title="${escapeHtml(value)}">Open →</a></td>`;
            } else {
                html += `<td title="${escapeHtml(value)}">${escapeHtml(truncate(value, 60))}</td>`;
            }
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
    document.getElementById('result-count').innerHTML = `Showing <strong>${data.results.length}</strong> results from <strong>${data.site_type}</strong>`;
}

function resetScrapeButton() {
    scrapeBtn.disabled = false;
    scrapeBtnText.textContent = 'Start Scraping';
    scrapeBtnSpinner.style.display = 'none';
}

function updateStats() {
    statJobs.textContent = totalJobs;
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
        const response = await fetch(`/api/export/${currentJobId}?sort=${sortSelect.value}`);

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
