#!/usr/bin/env python3
"""
Standalone Mind Map Server for JRVS
Serves the mind map visualization with mock data for testing.
Run this if the main JRVS server has dependency issues.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional
import aiosqlite

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Configuration
DATABASE_PATH = "data/jarvis.db"
PORT = 8080

app = FastAPI(title="JRVS Mind Map", description="Mind Map Memory Visualization")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


async def init_mindmap_tables():
    """Initialize mind map tables if they don't exist"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_name TEXT NOT NULL UNIQUE,
                category TEXT,
                first_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                mention_count INTEGER DEFAULT 1,
                embedding BLOB
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topic_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id_1 INTEGER,
                topic_id_2 INTEGER,
                strength REAL DEFAULT 0.0,
                co_occurrence_count INTEGER DEFAULT 0,
                relationship_type TEXT DEFAULT 'related',
                FOREIGN KEY (topic_id_1) REFERENCES topics(id),
                FOREIGN KEY (topic_id_2) REFERENCES topics(id),
                UNIQUE(topic_id_1, topic_id_2)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mindmap_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                graph_data TEXT,
                description TEXT
            )
        """)
        
        await db.commit()


@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    print("🧠 Initializing Mind Map server...")
    await init_mindmap_tables()
    print("✓ Mind Map tables ready")
    print(f"✓ Server running at http://localhost:{PORT}")
    print(f"✓ Mind Map UI: http://localhost:{PORT}/mindmap")


@app.get("/")
async def root():
    """Redirect to mind map"""
    return HTMLResponse(content="""
    <html>
    <head><meta http-equiv="refresh" content="0; url=/mindmap"></head>
    <body><p>Redirecting to <a href="/mindmap">Mind Map</a>...</p></body>
    </html>
    """)


@app.get("/mindmap")
async def mindmap_page():
    """Serve the mind map visualization UI"""
    with open("static/mindmap.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/mindmap/graph")
async def get_mindmap_graph(
    time_range: Optional[str] = "all",
    category: Optional[str] = None,
    min_connections: int = 0
):
    """Get mind map graph data"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Get topics
        query = "SELECT * FROM topics ORDER BY mention_count DESC"
        cursor = await db.execute(query)
        topics = await cursor.fetchall()
        
        # Get relationships
        cursor = await db.execute("""
            SELECT * FROM topic_relationships WHERE strength >= 0.3
        """)
        relationships = await cursor.fetchall()
        
        nodes = []
        for t in topics:
            if category and t['category'] != category:
                continue
            nodes.append({
                "id": t['id'],
                "label": t['topic_name'],
                "size": t['mention_count'],
                "category": t['category'] or 'other',
                "first_seen": t['first_mentioned'],
                "last_seen": t['last_mentioned']
            })
        
        node_ids = {n['id'] for n in nodes}
        
        edges = []
        for r in relationships:
            if r['topic_id_1'] in node_ids and r['topic_id_2'] in node_ids:
                edges.append({
                    "source": r['topic_id_1'],
                    "target": r['topic_id_2'],
                    "weight": r['strength'],
                    "type": r['relationship_type'] or 'related'
                })
        
        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "total_topics": len(nodes),
                "total_connections": len(edges),
                "generated_at": datetime.now().isoformat()
            }
        }


@app.get("/api/mindmap/topic/{topic_id}")
async def get_topic_details(topic_id: int):
    """Get detailed information about a specific topic"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        cursor = await db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
        topic = await cursor.fetchone()
        
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        
        # Get related topics
        cursor = await db.execute("""
            SELECT t.*, tr.strength
            FROM topics t
            JOIN topic_relationships tr ON 
                (tr.topic_id_1 = t.id AND tr.topic_id_2 = ?) OR
                (tr.topic_id_2 = t.id AND tr.topic_id_1 = ?)
            WHERE t.id != ?
            ORDER BY tr.strength DESC
            LIMIT 10
        """, (topic_id, topic_id, topic_id))
        related = await cursor.fetchall()
        
        return {
            "topic": {
                "id": topic['id'],
                "topic_name": topic['topic_name'],
                "category": topic['category'],
                "mention_count": topic['mention_count'],
                "first_mentioned": topic['first_mentioned'],
                "last_mentioned": topic['last_mentioned']
            },
            "conversations": [],  # Would need conversation_topics table
            "related_topics": [
                {"id": r['id'], "topic_name": r['topic_name'], "category": r['category'], "strength": r['strength']}
                for r in related
            ],
            "statistics": {
                "total_mentions": topic['mention_count'],
                "conversation_count": 0,
                "related_topics_count": len(related)
            }
        }


@app.post("/api/mindmap/build")
async def build_mindmap():
    """Build/rebuild the mind map (simplified without LLM)"""
    # For the standalone server, just return a message
    # The full build requires the LLM and embedding models
    return {
        "status": "info",
        "message": "Use the full JRVS server with '/mindmap build' command for LLM-powered topic extraction. This standalone server shows existing data only."
    }


@app.post("/api/mindmap/snapshot")
async def save_snapshot(snapshot_name: str, description: str = ""):
    """Save current mind map state"""
    graph = await get_mindmap_graph()
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO mindmap_snapshots (snapshot_name, graph_data, description) VALUES (?, ?, ?)",
            (snapshot_name, json.dumps(graph), description)
        )
        await db.commit()
        
        return {"snapshot_id": cursor.lastrowid, "message": "Snapshot saved"}


@app.get("/api/mindmap/snapshots")
async def list_snapshots():
    """List all saved snapshots"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT id, snapshot_name, created_at, description 
            FROM mindmap_snapshots ORDER BY created_at DESC
        """)
        snapshots = await cursor.fetchall()
        return [dict(s) for s in snapshots]


@app.get("/api/mindmap/insights")
async def get_insights():
    """Get basic insights (without LLM)"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Get stats
        cursor = await db.execute("SELECT COUNT(*) as count FROM topics")
        topic_count = (await cursor.fetchone())['count']
        
        cursor = await db.execute("SELECT COUNT(*) as count FROM topic_relationships")
        rel_count = (await cursor.fetchone())['count']
        
        cursor = await db.execute("""
            SELECT category, COUNT(*) as count FROM topics 
            GROUP BY category ORDER BY count DESC LIMIT 1
        """)
        top_cat = await cursor.fetchone()
        
        cursor = await db.execute("""
            SELECT topic_name, mention_count FROM topics 
            ORDER BY mention_count DESC LIMIT 1
        """)
        top_topic = await cursor.fetchone()
        
        insights = []
        
        if topic_count > 0:
            insights.append({
                "type": "Focus",
                "description": f"You have {topic_count} topics tracked in your mind map.",
                "icon": "🎯",
                "style": "cyan"
            })
        
        if top_cat:
            insights.append({
                "type": "Pattern",
                "description": f"Your most discussed category is '{top_cat['category']}' with {top_cat['count']} topics.",
                "icon": "🔍",
                "style": "cyan"
            })
        
        if top_topic:
            insights.append({
                "type": "Trend",
                "description": f"'{top_topic['topic_name']}' is your most mentioned topic ({top_topic['mention_count']} times).",
                "icon": "📈",
                "style": "cyan"
            })
        
        if rel_count > 0:
            insights.append({
                "type": "Connection",
                "description": f"Your topics have {rel_count} connections, showing how your knowledge areas relate.",
                "icon": "🔗",
                "style": "cyan"
            })
        
        if not insights:
            insights.append({
                "type": "Info",
                "description": "No data yet. Use '/mindmap build' in the full JRVS CLI to extract topics from your conversations.",
                "icon": "ℹ️",
                "style": "yellow"
            })
        
        return insights


@app.get("/api/mindmap/stats")
async def get_stats():
    """Get mind map statistics"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM topics")
        topic_count = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM topic_relationships")
        rel_count = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT AVG(mention_count) FROM topics")
        avg_mentions = (await cursor.fetchone())[0] or 0
        
        cursor = await db.execute("""
            SELECT category, COUNT(*) as count FROM topics 
            GROUP BY category ORDER BY count DESC LIMIT 1
        """)
        top_cat_row = await cursor.fetchone()
        top_category = top_cat_row[0] if top_cat_row else 'unknown'
        
        return {
            "total_topics": topic_count,
            "total_connections": rel_count,
            "avg_mentions": round(avg_mentions, 2),
            "top_category": top_category,
            "conversations_processed": 0
        }


@app.get("/api/mindmap/search")
async def search_topics(q: str):
    """Search topics by name"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT id, topic_name, category, mention_count
            FROM topics WHERE topic_name LIKE ?
            ORDER BY mention_count DESC LIMIT 20
        """, (f"%{q}%",))
        
        results = await cursor.fetchall()
        return [dict(r) for r in results]


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════╗
║           JRVS Mind Map Server (Standalone)               ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  🧠 Mind Map visualization server                        ║
║                                                           ║
║  URL: http://localhost:8080/mindmap                       ║
║                                                           ║
║  This is a standalone server for testing the Mind Map    ║
║  visualization. For full functionality (LLM-powered      ║
║  topic extraction), use the main JRVS server.            ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
