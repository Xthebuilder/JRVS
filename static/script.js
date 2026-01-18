// WebSocket connection
let ws = null;
let currentSessionId = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    connect();
    autoResizeTextarea();
});

// WebSocket Connection
function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

    ws.onopen = () => {
        updateStatus('Connected', true);
        console.log('Connected to JRVS');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };

    ws.onclose = () => {
        updateStatus('Disconnected', false);
        setTimeout(connect, 3000);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        updateStatus('Error', false);
    };
}

function updateStatus(text, connected) {
    const statusText = document.getElementById('statusText');
    const statusDot = document.querySelector('.status-dot');

    statusText.textContent = text;
    statusDot.style.background = connected ? '#10a37f' : '#ef4444';
}

// Message Handling
function handleMessage(data) {
    switch(data.type) {
        case 'system':
            if (data.session_id) {
                currentSessionId = data.session_id;
            }
            addSystemMessage(data.message);
            break;
        case 'status':
            showStatus(data.message);
            break;
        case 'tools':
            hideStatus();
            showToolsUsed(data.tools);
            break;
        case 'response':
            hideStatus();
            addAssistantMessage(data.message, data.timestamp);
            break;
        case 'error':
            hideStatus();
            addSystemMessage(`Error: ${data.message}`);
            break;
    }
}

// Message Display
function addUserMessage(text) {
    hideWelcomeScreen();
    const messagesDiv = document.getElementById('messages');

    const messageDiv = document.createElement('div');
    messageDiv.className = 'message';
    messageDiv.innerHTML = `
        <div class="message-header">
            <div class="message-avatar user-avatar">👤</div>
            <span class="message-role">You</span>
        </div>
        <div class="message-content">${escapeHtml(text)}</div>
    `;

    messagesDiv.appendChild(messageDiv);
    scrollToBottom();
}

function addAssistantMessage(text, timestamp) {
    hideWelcomeScreen();
    const messagesDiv = document.getElementById('messages');

    const messageDiv = document.createElement('div');
    messageDiv.className = 'message';

    const formattedText = formatMessage(text);
    const timeString = timestamp ? new Date(timestamp).toLocaleTimeString() : '';

    messageDiv.innerHTML = `
        <div class="message-header">
            <div class="message-avatar assistant-avatar">🤖</div>
            <span class="message-role">JRVS</span>
        </div>
        <div class="message-content">
            ${formattedText}
            ${timeString ? `<div class="timestamp">${timeString}</div>` : ''}
        </div>
    `;

    messagesDiv.appendChild(messageDiv);
    scrollToBottom();
}

function addSystemMessage(text) {
    hideWelcomeScreen();
    const messagesDiv = document.getElementById('messages');

    const messageDiv = document.createElement('div');
    messageDiv.className = 'system-message';
    messageDiv.textContent = text;

    messagesDiv.appendChild(messageDiv);
    scrollToBottom();
}

function showToolsUsed(tools) {
    const messagesDiv = document.getElementById('messages');

    const toolsDiv = document.createElement('div');
    toolsDiv.className = 'tools-badge';
    toolsDiv.innerHTML = `
        🔧 Tools Used: ${tools.join(', ')}
    `;

    messagesDiv.appendChild(toolsDiv);
    scrollToBottom();
}

function showStatus(text) {
    hideWelcomeScreen();
    hideStatus(); // Remove previous status

    const messagesDiv = document.getElementById('messages');

    const statusDiv = document.createElement('div');
    statusDiv.className = 'status-message';
    statusDiv.id = 'currentStatus';
    statusDiv.textContent = text;

    messagesDiv.appendChild(statusDiv);
    scrollToBottom();
}

function hideStatus() {
    const status = document.getElementById('currentStatus');
    if (status) status.remove();
}

function hideWelcomeScreen() {
    const welcome = document.getElementById('welcomeScreen');
    if (welcome) {
        welcome.style.display = 'none';
    }
}

// Message Formatting
function formatMessage(text) {
    // Simple markdown-like formatting
    let formatted = escapeHtml(text);

    // Code blocks
    formatted = formatted.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

    // Inline code
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Lists
    formatted = formatted.replace(/^- (.+)$/gm, '• $1');

    // Line breaks
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Sending Messages
function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();

    if (!message || !ws || ws.readyState !== WebSocket.OPEN) return;

    addUserMessage(message);
    ws.send(JSON.stringify({ message }));
    input.value = '';
    autoResizeTextarea();

    // Disable send button temporarily
    const sendBtn = document.getElementById('sendButton');
    sendBtn.disabled = true;
    setTimeout(() => sendBtn.disabled = false, 1000);
}

function sendQuickMessage(message) {
    document.getElementById('messageInput').value = message;
    sendMessage();
}

function quickCommand(command) {
    sendQuickMessage(command);
}

// Input Handling
function handleKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function autoResizeTextarea() {
    const textarea = document.getElementById('messageInput');
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

document.getElementById('messageInput').addEventListener('input', autoResizeTextarea);

// Utility
function scrollToBottom() {
    const container = document.getElementById('chatContainer');
    container.scrollTop = container.scrollHeight;
}

function newChat() {
    const messagesDiv = document.getElementById('messages');
    messagesDiv.innerHTML = '';
    document.getElementById('welcomeScreen').style.display = 'block';
}

// Sidebar
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('active');
}

// Modals
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    modal.classList.add('active');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    modal.classList.remove('active');
}

// Close modal on background click
document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
        }
    });
});

// Calendar
async function showCalendar() {
    openModal('calendarModal');
    const content = document.getElementById('calendarContent');
    content.innerHTML = 'Loading calendar...';

    try {
        const response = await fetch('/api/calendar/month');
        const data = await response.json();

        let html = `<div class="calendar-ascii">${data.calendar}</div>`;

        if (data.events && Object.keys(data.events).length > 0) {
            html += '<div class="event-list"><h3>Events this month:</h3>';

            for (const [day, events] of Object.entries(data.events).sort()) {
                events.forEach(event => {
                    const dt = new Date(event.event_date);
                    const status = event.completed ? '✓' : '○';
                    html += `
                        <div class="event-item">
                            <h4>${status} ${event.title}</h4>
                            <p>${dt.toLocaleDateString()} at ${dt.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</p>
                            ${event.description ? `<p>${event.description}</p>` : ''}
                        </div>
                    `;
                });
            }

            html += '</div>';
        }

        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<p>Error loading calendar: ${error.message}</p>`;
    }
}

function showAddEvent() {
    openModal('addEventModal');
    // Set default date to today
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('eventDate').value = today;
}

async function submitEvent(e) {
    e.preventDefault();

    const title = document.getElementById('eventTitle').value;
    const date = document.getElementById('eventDate').value;
    const time = document.getElementById('eventTime').value;
    const description = document.getElementById('eventDescription').value;

    try {
        const response = await fetch('/api/calendar/event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ title, date, time, description })
        });

        const data = await response.json();

        if (data.success) {
            closeModal('addEventModal');
            addSystemMessage(`✓ Event added: ${title} on ${date} at ${time}`);
            document.getElementById('eventForm').reset();
        } else {
            alert('Failed to add event');
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

// MCP
async function showMCPServers() {
    openModal('mcpModal');
    const content = document.getElementById('mcpContent');
    content.innerHTML = 'Loading MCP servers...';

    try {
        const response = await fetch('/api/mcp/servers');
        const data = await response.json();

        let html = '<h3>Connected Servers</h3>';

        if (data.servers && data.servers.length > 0) {
            html += '<div class="event-list">';
            data.servers.forEach(server => {
                const toolCount = data.tools_count[server] || 0;
                html += `
                    <div class="event-item">
                        <h4>🔌 ${server}</h4>
                        <p>${toolCount} tools available</p>
                        <button class="btn-primary" onclick="showServerTools('${server}')">View Tools</button>
                    </div>
                `;
            });
            html += '</div>';
        } else {
            html += '<p>No MCP servers connected</p>';
        }

        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<p>Error: ${error.message}</p>`;
    }
}

async function showMCPTools() {
    openModal('mcpModal');
    const content = document.getElementById('mcpContent');
    content.innerHTML = 'Loading tools...';

    try {
        const response = await fetch('/api/mcp/tools');
        const data = await response.json();

        let html = '<h3>Available MCP Tools</h3><div class="event-list">';

        for (const [server, tools] of Object.entries(data.tools)) {
            html += `<h4>🔌 ${server}</h4>`;
            tools.forEach(tool => {
                html += `
                    <div class="event-item">
                        <h4>🔧 ${tool.name}</h4>
                        <p>${tool.description || 'No description'}</p>
                    </div>
                `;
            });
        }

        html += '</div>';
        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<p>Error: ${error.message}</p>`;
    }
}

async function showServerTools(server) {
    const content = document.getElementById('mcpContent');
    content.innerHTML = 'Loading tools...';

    try {
        const response = await fetch(`/api/mcp/tools?server=${server}`);
        const data = await response.json();

        let html = `<h3>Tools from ${server}</h3><div class="event-list">`;

        if (data.tools && data.tools.length > 0) {
            data.tools.forEach(tool => {
                html += `
                    <div class="event-item">
                        <h4>🔧 ${tool.name}</h4>
                        <p>${tool.description || 'No description'}</p>
                    </div>
                `;
            });
        } else {
            html += '<p>No tools available</p>';
        }

        html += '</div>';
        html += `<button class="btn-primary" onclick="showMCPServers()">← Back to Servers</button>`;
        content.innerHTML = html;
    } catch (error) {
        content.innerHTML = `<p>Error: ${error.message}</p>`;
    }
}

// Models & Settings
async function showModels() {
    sendQuickMessage('/models');
}

function showThemes() {
    sendQuickMessage('/theme');
}

function showScraper() {
    const url = prompt('Enter URL to scrape:');
    if (url) {
        sendQuickMessage(`/scrape ${url}`);
    }
}

function showSettings() {
    sendQuickMessage('/stats');
}

function showAttachMenu() {
    alert('File attachment coming soon!');
}
