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
let currentApprovalThreadId = null;
let isWaitingForResponse = false;

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
        const file = e.dataTransfer.files[0];
        if (file) handleFileUpload(file);
    });

    fileInput.addEventListener('change', function() {
        if (this.files[0]) handleFileUpload(this.files[0]);
    });

    // Drive Link Upload
    document.getElementById('btn-drive-upload').addEventListener('click', () => {
        const link = document.getElementById('drive-link').value.trim();
        if (link) handleDriveLinkUpload(link);
    });

    // Upload Approval
    document.getElementById('btn-approve').addEventListener('click', () => sendUploadApproval('approved'));
    document.getElementById('btn-reject').addEventListener('click', () => sendUploadApproval('rejected'));

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
        addAssistantMessage(data);
        
        // If this was an upload response, reset UI
        if (data.query_type === 'upload') {
            document.getElementById('upload-status').classList.add('hidden');
            document.getElementById('upload-approval').classList.add('hidden');
            document.getElementById('file-input').value = '';
            document.getElementById('drive-link').value = '';
            
            // Switch back to chat to see the result
            switchTab('chat');
        }
    }
    else if (type === 'approval_request') {
        // Human-in-the-loop interrupt
        isWaitingForResponse = false;
        removeStatusIndicator();
        showUploadApproval(data);
    }
    else if (type === 'error') {
        isWaitingForResponse = false;
        removeStatusIndicator();
        showToast(data.message, 'error');
        
        document.getElementById('upload-status').classList.add('hidden');
    }
    
    // Update input state
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
// Upload Handling
// ═══════════════════════════════════════

function handleFileUpload(file) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showToast('Not connected to server', 'error');
        return;
    }
    
    // Read file as base64
    const reader = new FileReader();
    reader.onload = (e) => {
        const base64Data = e.target.result.split(',')[1]; // Remove data:mime/type;base64,
        
        document.getElementById('upload-status').classList.remove('hidden');
        document.getElementById('upload-status-text').textContent = 'Analyzing file...';
        document.getElementById('upload-approval').classList.add('hidden');
        
        ws.send(JSON.stringify({
            type: 'upload_file',
            filename: file.name,
            data: base64Data,
            session_id: sessionId
        }));
    };
    reader.readAsDataURL(file);
}

function handleDriveLinkUpload(link) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    
    document.getElementById('upload-status').classList.remove('hidden');
    document.getElementById('upload-status-text').textContent = 'Downloading from Drive...';
    document.getElementById('upload-approval').classList.add('hidden');
    
    ws.send(JSON.stringify({
        type: 'upload_link',
        link: link,
        session_id: sessionId
    }));
}

function showUploadApproval(data) {
    currentApprovalThreadId = data.thread_id;
    
    document.getElementById('upload-status').classList.add('hidden');
    const approvalCard = document.getElementById('upload-approval');
    const content = document.getElementById('approval-content');
    
    // Parse markdown if available
    content.innerHTML = window.marked ? marked.parse(data.message) : data.message;
    
    approvalCard.classList.remove('hidden');
    showToast('Action required: Confirm upload location', 'info');
}

function sendUploadApproval(decision) {
    if (!currentApprovalThreadId || !ws) return;
    
    document.getElementById('upload-approval').classList.add('hidden');
    document.getElementById('upload-status').classList.remove('hidden');
    document.getElementById('upload-status-text').textContent = 
        decision === 'approved' ? 'Uploading to Drive and indexing...' : 'Cancelling upload...';
    
    ws.send(JSON.stringify({
        type: 'upload_approval',
        decision: decision,
        thread_id: currentApprovalThreadId,
        session_id: sessionId
    }));
    
    currentApprovalThreadId = null;
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
        
        document.getElementById('stat-chunks').textContent = data.chroma.total_documents;
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
