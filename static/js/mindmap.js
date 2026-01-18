/**
 * JRVS Mind Map Visualization
 * Interactive D3.js force-directed graph for topic visualization
 */

class MindMapVisualization {
    constructor() {
        this.width = 0;
        this.height = 0;
        this.svg = null;
        this.simulation = null;
        this.nodes = [];
        this.edges = [];
        this.tooltip = null;
        
        // Category color scale
        this.colorScale = {
            'programming': '#6366f1',
            'research': '#22d3ee',
            'personal': '#f472b6',
            'work': '#f59e0b',
            'learning': '#10b981',
            'other': '#94a3b8'
        };
        
        this.init();
    }
    
    async init() {
        this.setupDimensions();
        this.setupSVG();
        this.setupTooltip();
        this.setupControls();
        this.setupLegend();
        
        await this.loadGraph();
        
        window.addEventListener('resize', () => this.handleResize());
    }
    
    setupDimensions() {
        const container = document.getElementById('graph-container');
        this.width = container.clientWidth;
        this.height = container.clientHeight;
    }
    
    setupSVG() {
        this.svg = d3.select("#mindmap")
            .attr("width", this.width)
            .attr("height", this.height);
        
        // Add zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on("zoom", (event) => {
                this.svg.select("g.graph-content")
                    .attr("transform", event.transform);
            });
        
        this.svg.call(zoom);
        
        // Create main group for graph content
        this.svg.append("g").attr("class", "graph-content");
        
        // Create arrow markers for directed edges
        const defs = this.svg.append("defs");
        
        ['related', 'same_category', 'co_discussed', 'semantically_similar'].forEach(type => {
            defs.append("marker")
                .attr("id", `arrow-${type}`)
                .attr("viewBox", "0 -5 10 10")
                .attr("refX", 25)
                .attr("refY", 0)
                .attr("markerWidth", 6)
                .attr("markerHeight", 6)
                .attr("orient", "auto")
                .append("path")
                .attr("d", "M0,-5L10,0L0,5")
                .attr("fill", "#666");
        });
        
        // Initialize simulation
        this.simulation = d3.forceSimulation()
            .force("link", d3.forceLink().id(d => d.id).distance(120))
            .force("charge", d3.forceManyBody().strength(-400))
            .force("center", d3.forceCenter(this.width / 2, this.height / 2))
            .force("collision", d3.forceCollide().radius(40))
            .force("x", d3.forceX(this.width / 2).strength(0.05))
            .force("y", d3.forceY(this.height / 2).strength(0.05));
    }
    
    setupTooltip() {
        this.tooltip = d3.select("body")
            .append("div")
            .attr("class", "tooltip")
            .style("opacity", 0)
            .style("display", "none");
    }
    
    setupControls() {
        // Time range filter
        document.getElementById('timeRange').addEventListener('change', (e) => {
            this.loadGraph({ time_range: e.target.value });
        });
        
        // Category filter
        document.getElementById('category').addEventListener('change', (e) => {
            this.loadGraph({ category: e.target.value });
        });
        
        // Min connections slider
        const slider = document.getElementById('minConnections');
        const sliderValue = document.getElementById('minConnectionsValue');
        
        slider.addEventListener('input', (e) => {
            sliderValue.textContent = e.target.value;
        });
        
        slider.addEventListener('change', (e) => {
            this.loadGraph({ min_connections: parseInt(e.target.value) });
        });
        
        // Action buttons
        document.getElementById('refreshBtn').addEventListener('click', () => {
            this.loadGraph();
        });
        
        document.getElementById('buildBtn').addEventListener('click', () => {
            this.buildGraph();
        });
        
        document.getElementById('snapshotBtn').addEventListener('click', () => {
            this.saveSnapshot();
        });
        
        document.getElementById('insightsBtn').addEventListener('click', () => {
            this.showInsights();
        });
        
        // Empty state build button
        document.getElementById('emptyBuildBtn')?.addEventListener('click', () => {
            this.buildGraph();
        });
        
        // Search
        document.getElementById('searchBtn').addEventListener('click', () => {
            this.searchTopics();
        });
        
        document.getElementById('searchInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.searchTopics();
        });
    }
    
    setupLegend() {
        const legend = document.getElementById('legend');
        legend.innerHTML = '';
        
        const categories = [
            { name: 'Programming', color: this.colorScale.programming },
            { name: 'Research', color: this.colorScale.research },
            { name: 'Personal', color: this.colorScale.personal },
            { name: 'Work', color: this.colorScale.work },
            { name: 'Learning', color: this.colorScale.learning },
            { name: 'Other', color: this.colorScale.other }
        ];
        
        categories.forEach(cat => {
            const item = document.createElement('div');
            item.className = 'legend-item';
            item.innerHTML = `
                <div class="legend-color" style="background-color: ${cat.color}"></div>
                <span>${cat.name}</span>
            `;
            legend.appendChild(item);
        });
    }
    
    async loadGraph(filters = {}) {
        this.showLoading(true);
        
        try {
            // Get current filter values if not provided
            const timeRange = filters.time_range || document.getElementById('timeRange').value;
            const category = filters.category !== undefined ? filters.category : document.getElementById('category').value;
            const minConnections = filters.min_connections !== undefined ? filters.min_connections : parseInt(document.getElementById('minConnections').value);
            
            const params = new URLSearchParams();
            if (timeRange) params.append('time_range', timeRange);
            if (category) params.append('category', category);
            if (minConnections > 0) params.append('min_connections', minConnections);
            
            const response = await fetch(`/api/mindmap/graph?${params}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.nodes && data.nodes.length > 0) {
                this.renderGraph(data);
                this.updateStats(data);
                document.getElementById('empty-state').classList.add('hidden');
            } else {
                this.showEmptyState();
            }
            
        } catch (error) {
            console.error('Error loading graph:', error);
            this.showToast('Error loading mind map', 'error');
            this.showEmptyState();
        } finally {
            this.showLoading(false);
        }
    }
    
    renderGraph(data) {
        const g = this.svg.select("g.graph-content");
        
        // Clear existing content
        g.selectAll("*").remove();
        
        this.nodes = data.nodes;
        this.edges = data.edges;
        
        // Create links
        const link = g.append("g")
            .attr("class", "links")
            .selectAll("line")
            .data(this.edges)
            .enter().append("line")
            .attr("class", "link")
            .attr("stroke-width", d => Math.sqrt(d.weight) * 2)
            .attr("stroke-opacity", d => 0.2 + d.weight * 0.5)
            .attr("marker-end", d => `url(#arrow-${d.type})`);
        
        // Create node groups
        const node = g.append("g")
            .attr("class", "nodes")
            .selectAll("g")
            .data(this.nodes)
            .enter().append("g")
            .attr("class", "node")
            .call(d3.drag()
                .on("start", (event, d) => this.dragStarted(event, d))
                .on("drag", (event, d) => this.dragged(event, d))
                .on("end", (event, d) => this.dragEnded(event, d))
            );
        
        // Add circles to nodes
        node.append("circle")
            .attr("r", d => Math.max(8, Math.sqrt(d.size) * 5))
            .attr("fill", d => this.colorScale[d.category] || this.colorScale.other)
            .attr("stroke", "#fff")
            .attr("stroke-width", 2)
            .on("click", (event, d) => this.showTopicDetails(d.id))
            .on("mouseover", (event, d) => this.showNodeTooltip(event, d))
            .on("mouseout", () => this.hideTooltip());
        
        // Add labels
        node.append("text")
            .text(d => this.truncateLabel(d.label, 20))
            .attr("x", d => Math.max(10, Math.sqrt(d.size) * 5) + 5)
            .attr("y", 4)
            .attr("font-size", "11px")
            .attr("fill", "#e0e0e0");
        
        // Update simulation
        this.simulation
            .nodes(this.nodes)
            .on("tick", () => {
                link
                    .attr("x1", d => d.source.x)
                    .attr("y1", d => d.source.y)
                    .attr("x2", d => d.target.x)
                    .attr("y2", d => d.target.y);
                
                node
                    .attr("transform", d => `translate(${d.x},${d.y})`);
            });
        
        this.simulation.force("link").links(this.edges);
        this.simulation.alpha(1).restart();
    }
    
    truncateLabel(label, maxLength) {
        if (label.length <= maxLength) return label;
        return label.substring(0, maxLength - 3) + '...';
    }
    
    showNodeTooltip(event, d) {
        this.tooltip
            .style("display", "block")
            .style("opacity", 1)
            .style("left", (event.pageX + 10) + "px")
            .style("top", (event.pageY - 10) + "px")
            .html(`
                <div class="tooltip-title">${d.label}</div>
                <div class="tooltip-info">
                    Category: ${d.category}<br>
                    Mentions: ${d.size}<br>
                    Click for details
                </div>
            `);
    }
    
    hideTooltip() {
        this.tooltip
            .style("opacity", 0)
            .style("display", "none");
    }
    
    async showTopicDetails(topicId) {
        try {
            const response = await fetch(`/api/mindmap/topic/${topicId}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            const panel = document.getElementById('details-panel');
            const title = document.getElementById('detailsTitle');
            const content = document.getElementById('detailsContent');
            
            title.textContent = data.topic.topic_name;
            
            let html = `
                <div class="detail-section">
                    <h4>Statistics</h4>
                    <ul>
                        <li>Category: <strong>${data.topic.category || 'Other'}</strong></li>
                        <li>Total Mentions: <strong>${data.statistics.total_mentions}</strong></li>
                        <li>Conversations: <strong>${data.statistics.conversation_count}</strong></li>
                        <li>Related Topics: <strong>${data.statistics.related_topics_count}</strong></li>
                    </ul>
                </div>
            `;
            
            if (data.conversations && data.conversations.length > 0) {
                html += `
                    <div class="detail-section">
                        <h4>Recent Conversations</h4>
                        <ul>
                `;
                
                data.conversations.slice(0, 5).forEach(conv => {
                    const date = new Date(conv.date).toLocaleDateString();
                    html += `<li>${conv.summary} <span class="timestamp">${date}</span></li>`;
                });
                
                html += `</ul></div>`;
            }
            
            if (data.related_topics && data.related_topics.length > 0) {
                html += `
                    <div class="detail-section">
                        <h4>Related Topics</h4>
                        <div class="related-topics">
                `;
                
                data.related_topics.forEach(topic => {
                    const color = this.colorScale[topic.category] || this.colorScale.other;
                    html += `<span class="topic-badge" style="background-color: ${color}">${topic.topic_name}</span>`;
                });
                
                html += `</div></div>`;
            }
            
            content.innerHTML = html;
            panel.classList.remove('hidden');
            
        } catch (error) {
            console.error('Error loading topic details:', error);
            this.showToast('Error loading topic details', 'error');
        }
    }
    
    async buildGraph() {
        this.showLoading(true);
        this.showToast('Building mind map from conversation history...', 'info');
        
        try {
            const response = await fetch('/api/mindmap/build', {
                method: 'POST'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const result = await response.json();
            
            this.showToast(result.message || 'Mind map built successfully!', 'success');
            
            // Reload the graph
            await this.loadGraph();
            
        } catch (error) {
            console.error('Error building graph:', error);
            this.showToast('Error building mind map', 'error');
        } finally {
            this.showLoading(false);
        }
    }
    
    async saveSnapshot() {
        const name = prompt("Enter snapshot name:");
        if (!name) return;
        
        try {
            const response = await fetch('/api/mindmap/snapshot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ snapshot_name: name })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const result = await response.json();
            this.showToast('Snapshot saved successfully!', 'success');
            
        } catch (error) {
            console.error('Error saving snapshot:', error);
            this.showToast('Error saving snapshot', 'error');
        }
    }
    
    async showInsights() {
        const modal = document.getElementById('insights-modal');
        const content = document.getElementById('insightsContent');
        
        content.innerHTML = '<div class="loading-indicator">Loading insights...</div>';
        modal.classList.remove('hidden');
        
        try {
            const response = await fetch('/api/mindmap/insights');
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const insights = await response.json();
            
            if (insights && insights.length > 0) {
                let html = '';
                insights.forEach(insight => {
                    html += `
                        <div class="insight-item">
                            <div class="insight-icon">${insight.icon || '📌'}</div>
                            <div class="insight-content">
                                <div class="insight-type">${insight.type}</div>
                                <div class="insight-description">${insight.description}</div>
                            </div>
                        </div>
                    `;
                });
                content.innerHTML = html;
            } else {
                content.innerHTML = '<p>No insights available yet. Build your mind map first!</p>';
            }
            
        } catch (error) {
            console.error('Error loading insights:', error);
            content.innerHTML = '<p>Error loading insights. Please try again.</p>';
        }
    }
    
    async searchTopics() {
        const searchInput = document.getElementById('searchInput');
        const searchResults = document.getElementById('searchResults');
        const query = searchInput.value.trim();
        
        if (!query) {
            searchResults.innerHTML = '';
            return;
        }
        
        try {
            const response = await fetch(`/api/mindmap/search?q=${encodeURIComponent(query)}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const results = await response.json();
            
            if (results && results.length > 0) {
                let html = '';
                results.forEach(topic => {
                    html += `
                        <div class="search-result-item" onclick="mindmap.focusOnTopic(${topic.id})">
                            <strong>${topic.topic_name}</strong>
                            <span class="text-muted"> (${topic.category})</span>
                        </div>
                    `;
                });
                searchResults.innerHTML = html;
            } else {
                searchResults.innerHTML = '<div class="search-result-item">No topics found</div>';
            }
            
        } catch (error) {
            console.error('Error searching topics:', error);
            searchResults.innerHTML = '<div class="search-result-item">Error searching</div>';
        }
    }
    
    focusOnTopic(topicId) {
        // Find the node
        const node = this.nodes.find(n => n.id === topicId);
        if (!node) return;
        
        // Animate to center on this node
        const transform = d3.zoomIdentity
            .translate(this.width / 2, this.height / 2)
            .scale(1.5)
            .translate(-node.x, -node.y);
        
        this.svg.transition()
            .duration(750)
            .call(d3.zoom().transform, transform);
        
        // Highlight the node
        this.showTopicDetails(topicId);
    }
    
    updateStats(data) {
        document.getElementById('topicCount').textContent = data.metadata.total_topics;
        document.getElementById('connectionCount').textContent = data.metadata.total_connections;
        
        // Calculate top category
        if (data.nodes.length > 0) {
            const categoryCounts = {};
            data.nodes.forEach(n => {
                categoryCounts[n.category] = (categoryCounts[n.category] || 0) + 1;
            });
            const topCat = Object.entries(categoryCounts)
                .sort((a, b) => b[1] - a[1])[0];
            document.getElementById('topCategory').textContent = topCat ? topCat[0] : '-';
        }
    }
    
    showLoading(show) {
        const loading = document.getElementById('loading');
        if (show) {
            loading.classList.remove('hidden');
        } else {
            loading.classList.add('hidden');
        }
    }
    
    showEmptyState() {
        document.getElementById('empty-state').classList.remove('hidden');
        this.svg.select("g.graph-content").selectAll("*").remove();
    }
    
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 4000);
    }
    
    handleResize() {
        this.setupDimensions();
        this.svg
            .attr("width", this.width)
            .attr("height", this.height);
        
        this.simulation
            .force("center", d3.forceCenter(this.width / 2, this.height / 2))
            .force("x", d3.forceX(this.width / 2).strength(0.05))
            .force("y", d3.forceY(this.height / 2).strength(0.05));
        
        this.simulation.alpha(0.3).restart();
    }
    
    // Drag handlers
    dragStarted(event, d) {
        if (!event.active) this.simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }
    
    dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }
    
    dragEnded(event, d) {
        if (!event.active) this.simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }
}

// Helper functions for closing panels
function closeDetails() {
    document.getElementById('details-panel').classList.add('hidden');
}

function closeInsights() {
    document.getElementById('insights-modal').classList.add('hidden');
}

// Initialize when page loads
let mindmap;
document.addEventListener('DOMContentLoaded', () => {
    mindmap = new MindMapVisualization();
});
