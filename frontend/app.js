/**
 * Frontend JavaScript for Course RAG
 * Handles UI state, WebSocket connectivity, and REST API calls.
 */

// ═══════════════════════════════════════
// State & Initialization
// ═══════════════════════════════════════

let authToken = localStorage.getItem('course_rag_token');
let sessionId = localStorage.getItem('course_rag_session') || crypto.randomUUID();
let ws = null;
let isWaitingForResponse = false;

// ── Upload batch state ──
let fileQueue = [];           // Array of File objects waiting to be uploaded
let fileTotalCount = 0;       // Total files in the current batch
let fileCurrentIndex = 0;     // Index of the file being processed right now

let driveLinkQueue = [];      // Array of Drive link strings waiting to be uploaded
let driveLinkTotalCount = 0;
let driveLinkCurrentIndex = 0;

let currentApprovalThreadId = null;   // thread_id for the file currently awaiting approval
let currentApprovalProposal = null;   // proposed_location from the server

// ── Path picker data ──
let uploadStructure = null;   // { structure: [{quarter, courses}], file_types: [] }

// Save session ID if newly generated
if (!localStorage.getItem('course_rag_session')) {
    localStorage.setItem('course_rag_session', sessionId);
}

// Config marked options for secure rendering
if (window.marked) {
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initUI();
    
    if (authToken) {
        verifyToken();
    } else {
        showScreen('login');
    }
});

// ═══════════════════════════════════════
// UI & Navigation
// ═══════════════════════════════════════

function initUI() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const pwd = document.getElementById('login-password').value;
        await login(pwd);
    });

    // Navigation
    document.querySelectorAll('.nav-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.getAttribute('data-tab');
            switchTab(tabName);
            if (tabName === 'admin') loadAdminStats();
        });
    });

    // Logout
    document.getElementById('btn-logout').addEventListener('click', logout);

    // Chat
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('btn-send');

    chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        sendBtn.disabled = this.value.trim().length === 0 || isWaitingForResponse;
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) sendChatMessage();
        }
    });

    sendBtn.addEventListener('click', sendChatMessage);

    // Chat chips
    document.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chatInput.value = chip.getAttribute('data-query');
            chatInput.dispatchEvent(new Event('input'));
            sendChatMessage();
        });
    });

    // Upload Drag & Drop
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');

    dropZone.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'), false);
    });

    dropZone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) startFileQueue(Array.from(files));
    });

    fileInput.addEventListener('change', function() {
        if (this.files.length > 0) startFileQueue(Array.from(this.files));
    });

    // Drive Link — seed the first row and wire up add/upload buttons
    addDriveLinkRow();
    document.getElementById('btn-add-drive-link').addEventListener('click', addDriveLinkRow);
    document.getElementById('btn-drive-upload').addEventListener('click', startDriveLinkQueue);

    // Upload Approval
    document.getElementById('btn-approve').addEventListener('click', () => sendUploadApproval('approved'));
    document.getElementById('btn-reject').addEventListener('click', showPathPicker);

    // Path Picker
    document.getElementById('picker-quarter').addEventListener('change', onPickerQuarterChange);
    document.getElementById('picker-course').addEventListener('change', updatePickerFullPath);
    document.getElementById('picker-filetype').addEventListener('change', updatePickerFullPath);
    document.getElementById('picker-filename').addEventListener('input', updatePickerFullPath);
    document.getElementById('btn-picker-confirm').addEventListener('click', confirmPathPicker);
    document.getElementById('btn-picker-cancel').addEventListener('click', cancelPathPicker);

    // Admin
    document.getElementById('btn-reembed').addEventListener('click', triggerReembed);
    document.getElementById('btn-cleanup').addEventListener('click', cleanupSessions);
}

function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(`${screenId}-screen`).classList.add('active');
}

function switchTab(tabId) {
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));
    document.getElementById(`tab-${tabId}`).classList.add('active');
    
    document.querySelectorAll('.panel').forEach(panel => panel.classList.remove('active'));
    document.getElementById(`panel-${tabId}`).classList.add('active');
}

// ═══════════════════════════════════════
// Authentication
// ═══════════════════════════════════════

async function login(password) {
    const btn = document.getElementById('login-btn');
    const err = document.getElementById('login-error');
    
    btn.innerHTML = '<div class="upload-spinner" style="width:18px;height:18px;margin:0"></div>';
    btn.disabled = true;
    err.textContent = '';

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ password })
        });
        
        const data = await res.json();
        
        if (data.success) {
            authToken = data.token;
            localStorage.setItem('course_rag_token', authToken);
            connectWebSocket();
            showScreen('app');
            showToast('Login successful', 'success');
        } else {
            err.textContent = 'Invalid password';
        }
    } catch (e) {
        err.textContent = 'Server error. Please try again.';
    } finally {
        btn.innerHTML = '<span>Sign In</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>';
        btn.disabled = false;
    }
}

async function verifyToken() {
    try {
        const res = await fetch('/api/verify', {
            headers: {'Authorization': `Bearer ${authToken}`}
        });
        
        if (res.ok) {
            connectWebSocket();
            showScreen('app');
        } else {
            logout();
        }
    } catch (e) {
        // If server is unreachable, just wait
        showScreen('login');
    }
}

function logout() {
    authToken = null;
    localStorage.removeItem('course_rag_token');
    if (ws) {
        ws.close();
        ws = null;
    }
    document.getElementById('login-password').value = '';
    showScreen('login');
}

// ═══════════════════════════════════════
// WebSocket & Chat
// ═══════════════════════════════════════

function connectWebSocket() {
    if (ws) ws.close();
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat?token=${authToken}`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        // Clear chat and load history if we wanted to (omitted for brevity)
    };
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleServerMessage(msg);
    };
    
    ws.onclose = (event) => {
        console.log('WebSocket disconnected', event.reason);
        if (event.code === 4001) {
            logout(); // Auth failed
        } else if (authToken) {
            // Reconnect attempt if not manually logged out
            setTimeout(connectWebSocket, 3000);
        }
    };
}

function handleServerMessage(message) {
    const { type, data } = message;

    if (type === 'status') {
        removeStatusIndicator();
        addStatusIndicator(data.message);
    }
    else if (type === 'response') {
        isWaitingForResponse = false;
        removeStatusIndicator();

        if (data.query_type === 'upload') {
            // Upload finished — hide all upload UI then move to the next queued item
            hideAllUploadCards();
            showToast(`Uploaded successfully`, 'success');
            processNextQueuedItem();
        } else {
            // Regular chat response
            addAssistantMessage(data);
        }
    }
    else if (type === 'approval_request') {
        isWaitingForResponse = false;
        removeStatusIndicator();
        currentApprovalThreadId = data.thread_id;
        currentApprovalProposal = data.proposed_location || null;
        showUploadApproval(data);
    }
    else if (type === 'error') {
        isWaitingForResponse = false;
        removeStatusIndicator();
        showToast(data.message, 'error');
        hideAllUploadCards();
        // On error, still advance the queue so remaining files are processed
        processNextQueuedItem();
    }

    // Update chat input button state
    document.getElementById('chat-input').dispatchEvent(new Event('input'));
}

function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    
    // Add to UI
    addHumanMessage(text);
    
    // Send
    isWaitingForResponse = true;
    ws.send(JSON.stringify({
        type: 'chat',
        message: text,
        session_id: sessionId
    }));
    
    // Clear input
    input.value = '';
    input.style.height = 'auto';
    input.dispatchEvent(new Event('input'));
}

// ═══════════════════════════════════════
// Upload — Batch Queue
// ═══════════════════════════════════════

function hideAllUploadCards() {
    document.getElementById('upload-status').classList.add('hidden');
    document.getElementById('upload-approval').classList.add('hidden');
    document.getElementById('path-picker').classList.add('hidden');
}

/** Called when there are no more items in either queue. */
function onBatchComplete() {
    hideAllUploadCards();
    document.getElementById('file-input').value = '';
    // Reset drive link rows to a single empty row
    document.getElementById('drive-links-container').innerHTML = '';
    addDriveLinkRow();
}

/** Advance to the next item across both queues (files first, then links). */
function processNextQueuedItem() {
    if (fileCurrentIndex < fileQueue.length) {
        processFileAt(fileCurrentIndex);
        fileCurrentIndex++;
    } else if (driveLinkCurrentIndex < driveLinkQueue.length) {
        processDriveLinkAt(driveLinkCurrentIndex);
        driveLinkCurrentIndex++;
    } else {
        onBatchComplete();
    }
}

// ── File uploads ──

function startFileQueue(files) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showToast('Not connected to server', 'error');
        return;
    }
    fileQueue = files;
    fileTotalCount = files.length;
    fileCurrentIndex = 0;
    driveLinkQueue = [];
    driveLinkCurrentIndex = 0;
    processNextQueuedItem();
}

function processFileAt(index) {
    const file = fileQueue[index];
    const label = fileTotalCount > 1
        ? `File ${index + 1} of ${fileTotalCount}: ${file.name}`
        : file.name;

    const reader = new FileReader();
    reader.onload = (e) => {
        const base64Data = e.target.result.split(',')[1];
        hideAllUploadCards();
        document.getElementById('upload-status').classList.remove('hidden');
        document.getElementById('upload-status-text').textContent = `${label} — Analyzing...`;

        ws.send(JSON.stringify({
            type: 'upload_file',
            filename: file.name,
            data: base64Data,
            session_id: sessionId,
        }));
    };
    reader.readAsDataURL(file);
}

// ── Drive link uploads ──

function addDriveLinkRow() {
    const container = document.getElementById('drive-links-container');
    const rowIndex = container.children.length;
    const row = document.createElement('div');
    row.className = 'drive-link-row';
    row.innerHTML = `
        <input type="url" class="drive-link-input" placeholder="https://drive.google.com/file/d/..." data-index="${rowIndex}">
        <button class="btn-remove-link" title="Remove" data-row>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
        </button>
    `;
    row.querySelector('[data-row]').addEventListener('click', () => {
        // Only allow removal if more than one row exists
        if (document.getElementById('drive-links-container').children.length > 1) {
            row.remove();
        }
    });
    container.appendChild(row);
}

function getDriveLinks() {
    return Array.from(
        document.querySelectorAll('#drive-links-container .drive-link-input')
    ).map(el => el.value.trim()).filter(v => v);
}

function startDriveLinkQueue() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showToast('Not connected to server', 'error');
        return;
    }
    const links = getDriveLinks();
    if (links.length === 0) {
        showToast('Please enter at least one Drive link', 'warning');
        return;
    }
    driveLinkQueue = links;
    driveLinkTotalCount = links.length;
    driveLinkCurrentIndex = 0;
    fileQueue = [];
    fileCurrentIndex = 0;
    processNextQueuedItem();
}

function processDriveLinkAt(index) {
    const link = driveLinkQueue[index];
    const label = driveLinkTotalCount > 1
        ? `Link ${index + 1} of ${driveLinkTotalCount}`
        : 'Drive file';

    hideAllUploadCards();
    document.getElementById('upload-status').classList.remove('hidden');
    document.getElementById('upload-status-text').textContent = `${label} — Downloading from Drive...`;

    ws.send(JSON.stringify({
        type: 'upload_link',
        link: link,
        session_id: sessionId,
    }));
}

// ── Approval card ──

function showUploadApproval(data) {
    hideAllUploadCards();
    const content = document.getElementById('approval-content');
    content.innerHTML = window.marked ? marked.parse(data.message) : data.message;
    document.getElementById('upload-approval').classList.remove('hidden');
    showToast('Action required: Confirm upload location', 'info');
}

function sendUploadApproval(decision, customLocation) {
    if (!currentApprovalThreadId || !ws) return;

    hideAllUploadCards();
    document.getElementById('upload-status').classList.remove('hidden');
    document.getElementById('upload-status-text').textContent =
        decision === 'rejected' ? 'Skipping file...' : 'Uploading to Drive and indexing...';

    const payload = {
        type: 'upload_approval',
        decision: decision,
        thread_id: currentApprovalThreadId,
        session_id: sessionId,
    };
    if (customLocation) payload.custom_location = customLocation;

    ws.send(JSON.stringify(payload));
    currentApprovalThreadId = null;
    currentApprovalProposal = null;
}

// ═══════════════════════════════════════
// Path Picker
// ═══════════════════════════════════════

async function loadUploadStructure() {
    if (uploadStructure) return uploadStructure;
    try {
        const res = await fetch('/api/admin/upload/structure', {
            headers: { 'Authorization': `Bearer ${authToken}` },
        });
        if (res.ok) {
            uploadStructure = await res.json();
        }
    } catch (e) {
        console.error('Failed to load upload structure', e);
    }
    return uploadStructure;
}

async function showPathPicker() {
    document.getElementById('upload-approval').classList.add('hidden');

    const structure = await loadUploadStructure();

    // Populate quarter dropdown
    const qSel = document.getElementById('picker-quarter');
    qSel.innerHTML = '';
    if (structure) {
        structure.structure.forEach(q => {
            const opt = document.createElement('option');
            opt.value = q.quarter;
            opt.textContent = q.quarter;
            qSel.appendChild(opt);
        });
    }

    // Pre-fill from LLM proposal
    const proposal = currentApprovalProposal || {};
    if (proposal.quarter) qSel.value = proposal.quarter;

    // Populate courses for the selected quarter
    populatePickerCourses(proposal.course_id);

    // Pre-fill file type
    const ftSel = document.getElementById('picker-filetype');
    if (proposal.file_type) ftSel.value = proposal.file_type;

    // Pre-fill filename from current file in queue
    const filenameInput = document.getElementById('picker-filename');
    const currentFile = fileQueue.length > 0 ? fileQueue[fileCurrentIndex - 1] : null;
    filenameInput.value = proposal.filename || (currentFile ? currentFile.name : '');

    // Update the editable full path
    if (proposal.full_path) {
        document.getElementById('picker-fullpath').value = proposal.full_path;
    } else {
        updatePickerFullPath();
    }

    // Reset validation message
    const msg = document.getElementById('picker-validation-msg');
    msg.textContent = '';
    msg.classList.add('hidden');

    document.getElementById('path-picker').classList.remove('hidden');
}

function populatePickerCourses(preselect) {
    const qSel = document.getElementById('picker-quarter');
    const cSel = document.getElementById('picker-course');
    cSel.innerHTML = '';

    if (!uploadStructure) return;

    const quarter = uploadStructure.structure.find(q => q.quarter === qSel.value);
    if (!quarter) return;

    quarter.courses.forEach(c => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify(c);  // store full course object as JSON
        opt.textContent = `${c.code}: ${c.name}`;
        cSel.appendChild(opt);
    });

    // Pre-select if we have a course_id hint
    if (preselect) {
        for (const opt of cSel.options) {
            try {
                if (JSON.parse(opt.value).code === preselect) {
                    cSel.value = opt.value;
                    break;
                }
            } catch (_) {}
        }
    }

    updatePickerFullPath();
}

function onPickerQuarterChange() {
    populatePickerCourses(null);
}

function updatePickerFullPath() {
    const quarter = document.getElementById('picker-quarter').value;
    const courseRaw = document.getElementById('picker-course').value;
    const fileType = document.getElementById('picker-filetype').value;
    const filename = document.getElementById('picker-filename').value.trim();

    let courseFolderName = '';
    try {
        const course = JSON.parse(courseRaw);
        courseFolderName = course.folder_name;
    } catch (_) {}

    if (quarter && courseFolderName && fileType && filename) {
        document.getElementById('picker-fullpath').value =
            `${quarter}/${courseFolderName}/${fileType}/${filename}`;
    }
}

async function confirmPathPicker() {
    const fullPath = document.getElementById('picker-fullpath').value.trim();
    if (!fullPath) {
        showPickerValidation('Please enter a full path.', false);
        return;
    }

    // Parse the path to extract structured fields
    const parts = fullPath.split('/');
    if (parts.length < 4) {
        showPickerValidation('Path must have format: Quarter/Course:Name/type/filename', false);
        return;
    }

    const quarter = parts[0];
    const coursePart = parts[1];      // e.g. MSA408:Operations_Analytics
    const fileType = parts[2];
    const filename = parts.slice(3).join('/');  // allows filenames with slashes (unlikely but safe)
    const folderPath = parts.slice(0, 3).join('/');

    // Validate the folder exists in Drive
    showPickerValidation('Validating path in Drive...', null);
    document.getElementById('btn-picker-confirm').disabled = true;

    try {
        const res = await fetch('/api/admin/upload/validate-path', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ path: folderPath }),
        });
        const data = await res.json();

        if (!data.valid) {
            showPickerValidation(
                `Folder "${folderPath}" does not exist in Drive. Check the path and try again.`,
                false
            );
            document.getElementById('btn-picker-confirm').disabled = false;
            return;
        }
    } catch (e) {
        showPickerValidation('Could not validate path. Check your connection.', false);
        document.getElementById('btn-picker-confirm').disabled = false;
        return;
    }

    document.getElementById('btn-picker-confirm').disabled = false;

    // Build the course_id and course_name from the coursePart
    const colonIdx = coursePart.indexOf(':');
    const courseCode = colonIdx >= 0 ? coursePart.slice(0, colonIdx) : coursePart;
    const courseName = colonIdx >= 0 ? coursePart.slice(colonIdx + 1) : '';

    const customLocation = {
        quarter,
        course_id: courseCode,
        course_name: courseName,
        file_type: fileType,
        filename,
        full_path: fullPath,
    };

    document.getElementById('path-picker').classList.add('hidden');
    sendUploadApproval('custom', customLocation);
}

function cancelPathPicker() {
    document.getElementById('path-picker').classList.add('hidden');
    // Skip this file — send a rejected decision then advance the queue
    if (currentApprovalThreadId) {
        sendUploadApproval('rejected');
    } else {
        processNextQueuedItem();
    }
}

function showPickerValidation(msg, isOk) {
    const el = document.getElementById('picker-validation-msg');
    el.textContent = msg;
    el.className = 'picker-validation';
    if (isOk === true) el.classList.add('valid');
    else if (isOk === false) el.classList.add('error');
    el.classList.remove('hidden');
}

// ═══════════════════════════════════════
// Chat DOM Updates
// ═══════════════════════════════════════

function addHumanMessage(text) {
    const container = document.getElementById('chat-messages');
    
    const div = document.createElement('div');
    div.className = 'message human';
    div.innerHTML = `
        <div class="message-bubble">${text.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>
        <div class="message-meta">You</div>
    `;
    
    container.appendChild(div);
    scrollToBottom();
}

function addAssistantMessage(data) {
    const container = document.getElementById('chat-messages');
    
    let htmlContent = window.marked ? marked.parse(data.message) : data.message.replace(/\n/g, '<br>');
    
    const div = document.createElement('div');
    div.className = 'message assistant';
    
    let metaHtml = `<div class="message-meta">`;
    metaHtml += `<span class="role-badge">Course RAG</span>`;
    if (data.query_type && data.query_type !== 'unknown') {
        metaHtml += `<span class="query-type-badge">${data.query_type}</span>`;
    }
    metaHtml += `</div>`;
    
    div.innerHTML = `
        <div class="message-bubble">${htmlContent}</div>
        ${metaHtml}
    `;
    
    container.appendChild(div);
    scrollToBottom();
}

function addStatusIndicator(text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.id = 'status-indicator';
    div.className = 'status-indicator';
    div.innerHTML = `
        <div class="pulse-dot"></div>
        <div style="font-size: 13px; color: var(--text-secondary)">${text}</div>
    `;
    container.appendChild(div);
    scrollToBottom();
}

function removeStatusIndicator() {
    const el = document.getElementById('status-indicator');
    if (el) el.remove();
}

function scrollToBottom() {
    const container = document.getElementById('chat-messages');
    container.scrollTop = container.scrollHeight;
}

// ═══════════════════════════════════════
// Admin Panel
// ═══════════════════════════════════════

let reembedInterval;

async function loadAdminStats() {
    try {
        const res = await fetch('/api/admin/stats', {
            headers: {'Authorization': `Bearer ${authToken}`}
        });
        const data = await res.json();
        
        document.getElementById('stat-chunks').textContent = data.chroma.total_chunks;
        document.getElementById('stat-files').textContent = data.chroma.unique_files;
        document.getElementById('stat-courses').textContent = data.config.courses.length;
        document.getElementById('stat-sessions').textContent = data.sessions.active_count;
        
        // Render config grid
        const grid = document.getElementById('config-grid');
        grid.innerHTML = `
            <div class="config-item"><div class="config-key">Current Quarter</div><div class="config-val">${data.config.current_quarter}</div></div>
            <div class="config-item"><div class="config-key">Claude Model</div><div class="config-val">${data.config.claude_model}</div></div>
            <div class="config-item"><div class="config-key">Embedding Model</div><div class="config-val">${data.config.embedding_model}</div></div>
            <div class="config-item"><div class="config-key">Chroma DB</div><div class="config-val">Ready</div></div>
        `;
        
    } catch (e) {
        showToast('Failed to load admin stats', 'error');
    }
}

async function triggerReembed() {
    const quarter = document.getElementById('reembed-quarter').value;
    const btn = document.getElementById('btn-reembed');
    
    btn.disabled = true;
    
    try {
        const res = await fetch('/api/admin/reembed', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ quarter: quarter, clear_existing: true })
        });
        
        if (res.ok) {
            showToast('Re-embedding started in background', 'info');
            document.getElementById('reembed-progress').classList.remove('hidden');
            reembedInterval = setInterval(pollReembedStatus, 1000);
        } else {
            const data = await res.json();
            showToast(data.detail || 'Failed to start', 'error');
            btn.disabled = false;
        }
    } catch (e) {
        showToast('Error connecting to server', 'error');
        btn.disabled = false;
    }
}

async function pollReembedStatus() {
    try {
        const res = await fetch('/api/admin/reembed/status', {
            headers: {'Authorization': `Bearer ${authToken}`}
        });
        const data = await res.json();
        
        const pct = Math.round(data.progress * 100);
        document.getElementById('reembed-fill').style.width = `${pct}%`;
        document.getElementById('reembed-text').textContent = data.message;
        
        if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(reembedInterval);
            document.getElementById('btn-reembed').disabled = false;
            
            if (data.status === 'completed') {
                showToast('Re-embedding completed successfully', 'success');
                setTimeout(() => document.getElementById('reembed-progress').classList.add('hidden'), 5000);
                loadAdminStats(); // Refresh stats
            } else {
                showToast(`Re-embedding failed: ${data.message}`, 'error');
            }
        }
    } catch (e) {
        // Ignore polling errors
    }
}

async function cleanupSessions() {
    try {
        const res = await fetch('/api/admin/sessions/cleanup', {
            method: 'POST',
            headers: {'Authorization': `Bearer ${authToken}`}
        });
        const data = await res.json();
        showToast(data.message, 'success');
        loadAdminStats();
    } catch (e) {
        showToast('Failed to clean up sessions', 'error');
    }
}

// ═══════════════════════════════════════
// Utilities
// ═══════════════════════════════════════

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '❌';
    
    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
