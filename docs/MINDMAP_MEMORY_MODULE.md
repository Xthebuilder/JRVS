# 🧠 Mind Map Memory Module

## Overview

The Mind Map Memory Module is a powerful visualization and analysis system that transforms your conversation history with JRVS into an interactive, topic-based knowledge graph. It helps you understand how your interests connect, track knowledge evolution over time, and discover hidden patterns in your interactions.

![Mind Map Concept](https://img.shields.io/badge/Feature-Mind%20Map-purple?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-green?style=for-the-badge)

## Features

### 🎯 Core Capabilities

| Feature | Description |
|---------|-------------|
| **Topic Extraction** | LLM-powered analysis extracts meaningful topics from conversations |
| **Relationship Mapping** | Automatically discovers connections between topics |
| **Interactive Visualization** | D3.js force-directed graph with zoom, pan, and click interactions |
| **Category Clustering** | Topics are grouped by category with visual color coding |
| **Temporal Tracking** | See when topics were first and last discussed |
| **Semantic Search** | Find topics using natural language queries |
| **Snapshot System** | Save and restore mind map states over time |
| **AI Insights** | Get intelligent analysis of your knowledge patterns |

### 🎨 Visual Design

- **Dark Theme**: Easy on the eyes with a modern aesthetic
- **Color-Coded Categories**: 
  - 🟣 Programming (Purple)
  - 🔵 Research (Blue)
  - 🟢 Personal (Green)
  - 🟡 Work (Yellow)
  - 🔴 Creative (Red)
  - ⚪ Other (Gray)
- **Dynamic Node Sizing**: Larger nodes = more frequently discussed topics
- **Animated Connections**: Edge thickness represents relationship strength
- **Hover Effects**: Highlight connected nodes on mouse over

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      JRVS Mind Map System                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   CLI        │    │   Web UI     │    │   API        │       │
│  │  /mindmap    │    │  D3.js Graph │    │  REST/WS     │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │                │
│         └───────────────────┼───────────────────┘                │
│                             │                                    │
│                    ┌────────▼────────┐                           │
│                    │  Memory Map     │                           │
│                    │  Module         │                           │
│                    └────────┬────────┘                           │
│                             │                                    │
│         ┌───────────────────┼───────────────────┐                │
│         │                   │                   │                │
│  ┌──────▼───────┐    ┌──────▼───────┐    ┌──────▼───────┐       │
│  │ Topic        │    │ Graph        │    │ Analyzer     │       │
│  │ Extractor    │    │ Builder      │    │              │       │
│  │ (LLM)        │    │ (NetworkX)   │    │ (Insights)   │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                             │                                    │
│                    ┌────────▼────────┐                           │
│                    │  SQLite DB      │                           │
│                    │  (topics,       │                           │
│                    │   relationships,│                           │
│                    │   snapshots)    │                           │
│                    └─────────────────┘                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

The Mind Map module is included with JRVS. No additional installation required.

### Dependencies (auto-installed)

```
networkx>=3.0      # Graph algorithms
aiosqlite          # Async SQLite operations
fastapi            # Web API framework
uvicorn            # ASGI server
```

## Quick Start

### 1. Start the Mind Map Server

```bash
# Option A: Standalone server (recommended for testing)
python3 mindmap_server.py

# Option B: Full JRVS server
python3 web_server.py
```

### 2. Access the Web UI

Open in your browser:
```
http://localhost:8080/mindmap
```

### 3. CLI Commands

```bash
# View the mind map (opens browser)
/mindmap view

# Build/rebuild the mind map from conversations
/mindmap build

# List all topics
/mindmap topics

# Search for a topic
/mindmap search machine learning

# Save a snapshot
/mindmap snapshot my-checkpoint

# Get AI-powered insights
/mindmap insights

# View statistics
/mindmap stats
```

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/mindmap/graph` | Get full graph data (nodes & edges) |
| `GET` | `/api/mindmap/topic/{id}` | Get topic details |
| `GET` | `/api/mindmap/search?q=` | Search topics |
| `GET` | `/api/mindmap/stats` | Get statistics |
| `GET` | `/api/mindmap/insights` | Get AI insights |
| `GET` | `/api/mindmap/snapshots` | List all snapshots |
| `POST` | `/api/mindmap/build` | Rebuild mind map |
| `POST` | `/api/mindmap/snapshot` | Save snapshot |

### Query Parameters

**GET /api/mindmap/graph**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `time_range` | string | `all` | Filter by time: `day`, `week`, `month`, `all` |
| `category` | string | `null` | Filter by category |
| `min_connections` | int | `0` | Minimum connections to include |

### Response Format

```json
{
  "nodes": [
    {
      "id": 1,
      "label": "Python async programming",
      "size": 5,
      "category": "programming",
      "first_seen": "2026-01-15T10:30:00",
      "last_seen": "2026-01-17T14:20:00"
    }
  ],
  "edges": [
    {
      "source": 1,
      "target": 2,
      "weight": 0.85,
      "type": "same_category"
    }
  ],
  "metadata": {
    "total_topics": 7,
    "total_connections": 6,
    "generated_at": "2026-01-17T15:00:00"
  }
}
```

## Database Schema

### Topics Table

```sql
CREATE TABLE topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_name TEXT NOT NULL UNIQUE,
    category TEXT,
    first_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mention_count INTEGER DEFAULT 1,
    embedding BLOB
);
```

### Relationships Table

```sql
CREATE TABLE topic_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id_1 INTEGER,
    topic_id_2 INTEGER,
    strength REAL DEFAULT 0.0,
    co_occurrence_count INTEGER DEFAULT 0,
    relationship_type TEXT DEFAULT 'related',
    FOREIGN KEY (topic_id_1) REFERENCES topics(id),
    FOREIGN KEY (topic_id_2) REFERENCES topics(id),
    UNIQUE(topic_id_1, topic_id_2)
);
```

### Snapshots Table

```sql
CREATE TABLE mindmap_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    graph_data TEXT,
    description TEXT
);
```

## Usage Examples

### Building Your Mind Map

When you first start using the Mind Map, run the build command to extract topics from your conversation history:

```
/mindmap build
```

This will:
1. Scan your conversation history
2. Use the LLM to extract meaningful topics
3. Categorize each topic
4. Analyze co-occurrence patterns
5. Build relationship connections
6. Calculate connection strengths

### Exploring Connections

Click on any node in the visualization to:
- See full topic details
- View related topics
- Access linked conversations
- See mention statistics

### Tracking Knowledge Evolution

Use snapshots to track how your knowledge map changes over time:

```
/mindmap snapshot january-2026
```

Compare snapshots to see:
- New topics added
- Strengthened connections
- Emerging interest areas
- Declining topics

### Getting Insights

The AI analyzer can identify patterns in your knowledge:

```
/mindmap insights
```

Sample insights:
- "Your focus on machine learning has grown 40% this month"
- "Python and data visualization are becoming a strong cluster"
- "Consider exploring the gap between your research and work topics"

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `R` | Reset zoom to fit all nodes |
| `F` | Toggle fullscreen |
| `S` | Save snapshot |
| `Esc` | Close details panel |
| `+` / `-` | Zoom in/out |

## Customization

### Adding Categories

Edit the category colors in `static/js/mindmap.js`:

```javascript
this.categoryColors = {
    programming: '#9b59b6',
    research: '#3498db',
    personal: '#2ecc71',
    work: '#f39c12',
    creative: '#e74c3c',
    other: '#95a5a6'
};
```

### Adjusting Physics

Modify force simulation parameters:

```javascript
this.simulation = d3.forceSimulation()
    .force('charge', d3.forceManyBody().strength(-300))
    .force('link', d3.forceLink().distance(100))
    .force('center', d3.forceCenter());
```

## Troubleshooting

### Mind Map Won't Load

1. Check if the server is running:
   ```bash
   curl http://localhost:8080/api/mindmap/stats
   ```

2. Check server logs:
   ```bash
   cat mindmap_server.log
   ```

3. Restart the server:
   ```bash
   pkill -f mindmap_server.py
   python3 mindmap_server.py
   ```

### No Topics Showing

1. Ensure you have conversation history
2. Run the build command:
   ```
   /mindmap build
   ```

### Graph Performance Issues

For large graphs (100+ nodes):
- Increase `min_connections` filter
- Filter by category
- Use time range filters

## Contributing

To extend the Mind Map module:

1. **Add new relationship types** in `memory_map/graph_builder.py`
2. **Customize topic extraction** in `memory_map/topic_extractor.py`
3. **Add new visualizations** in `static/js/mindmap.js`
4. **Extend insights** in `memory_map/analyzer.py`

## Roadmap

- [ ] 3D visualization mode
- [ ] Topic merging/splitting
- [ ] Export to various formats (PNG, SVG, JSON)
- [ ] Collaborative mind maps
- [ ] Integration with external knowledge bases
- [ ] Topic suggestion system
- [ ] Automated topic cleanup

## License

Part of JRVS - Your Personal AI Assistant

---

*"Map your mind, unlock your potential."* 🧠✨
