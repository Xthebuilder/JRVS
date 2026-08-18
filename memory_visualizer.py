import sqlite3
import json
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="JRVS Semantic Memory Visualizer")
app.mount("/static", StaticFiles(directory="public"), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("public/memory-visualizer.html", "r") as f:
        return f.read()

@app.get("/api/memory-graph")
async def get_memory_graph(conv_limit: int = 500, doc_limit: int = 150):
    conn = sqlite3.connect("data/jarvis.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    nodes = []
    edges = []
    
    try:
        # We simulate logical strength by analyzing chronological proximity, text length, and interaction counts
        # (Since pure FAISS high-dimensional vector math inside SQLite without an extension is impossible, 
        # we calculate proxy "Semantic Weight")
        
        cursor.execute("SELECT id, session_id, user_message, ai_response, created_at FROM conversations ORDER BY created_at ASC LIMIT ?", (conv_limit,))
        rows = cursor.fetchall()
        
        session_last_node = {} 
        for row in rows:
            sess = row['session_id'] or "default"
            node_id = f"conv_{row['id']}"
            
            # Artificial "Weight" based on how deep the conversation went (length of thought)
            msg_len = len(row['user_message'] or "") + len(row['ai_response'] or "")
            # Node Size: bigger if it contains more cognitive data
            calculated_size = 5 + (min(msg_len, 2000) / 200) 
            
            nodes.append({
                "id": node_id,
                "label": f"Chat ({sess[:6]})",
                "details": f"Date: {row['created_at']}\nSession: {sess}\nCognitive Load: {msg_len} bytes\n\nUSER:\n{row['user_message']}\n\nAI:\n{row['ai_response']}",
                "group": "conversation",
                "val": calculated_size, # This tells 3d-force-graph exactly how big to make the sphere
                "color": "#00e5ff"
            })
            
            if sess in session_last_node:
                prev_id = session_last_node[sess]
                # Edge thickness represents connection strength
                # For chronological thoughts in same session, we lock thickness at 2
                edges.append({
                    "from": prev_id,
                    "to": node_id,
                    "thickness": 1.5,
                    "type": "chronological"
                })
            session_last_node[sess] = node_id
                
        # Documents
        cursor.execute("SELECT id, filename, mime_type, content, created_at FROM documents LIMIT ?", (doc_limit,))
        doc_rows = cursor.fetchall()
        for doc in doc_rows:
            doc_id = f"doc_{doc['id']}"
            content_len = len(doc['content'] or '')
            calculated_val = 8 + (min(content_len, 10000) / 500) # Heavy root nodes
            
            nodes.append({
                "id": doc_id,
                "label": f"Doc: {doc['filename'][:15]}",
                "details": f"File: {doc['filename']}\nSize: {content_len} chars\n\nExcerpts:\n{(doc['content'] or '')[:1000]}...",
                "group": "document",
                "val": calculated_val,
                "color": "#9933ff"
            })
            
            # Document Vectors
            cursor.execute("SELECT id, content FROM document_chunks WHERE document_id = ? LIMIT 15", (doc['id'],))
            chunks = cursor.fetchall()
            for chunk in chunks:
                chunk_id = f"chunk_{chunk['id']}"
                chunk_len = len(chunk['content'])
                
                nodes.append({
                    "id": chunk_id,
                    "label": f"Vector {chunk['id']}",
                    "details": chunk['content'],
                    "group": "chunk",
                    "val": 2 + (chunk_len / 200), # Smaller fragmentation
                    "color": "#ffcc00"
                })
                # The strength of a Vector to its Parent Doc is heavily weighted based on size
                weight = 0.5 + (chunk_len / 500)
                edges.append({
                    "from": doc_id, 
                    "to": chunk_id,
                    "thickness": weight,
                    "type": "semantic"
                }) 
                
        # Goals
        try:
            cursor.execute("SELECT goal_id, plan_json, status, started_at, last_error FROM goal_state LIMIT 50")
            goals = cursor.fetchall()
            for goal in goals:
                # Active goals are heavier/bigger nodes inherently
                base_weight = 15 if goal['status'] == 'in_progress' else 10
                
                nodes.append({
                    "id": f"goal_{goal['goal_id']}",
                    "label": f"Goal [{goal['status']}]",
                    "details": f"Status: {goal['status']}\nStarted: {goal['started_at']}\nPlan:\n{goal['plan_json']}",
                    "group": "goal",
                    "val": base_weight,
                    "color": "#33cc33"
                })
        except:
            pass
            
        # Cross-Semantic Link Synthesis (Fake Vector Proximity for UI purposes)
        # Because we dropped the FAISS blobs, we will link random Docs to random Conversations 
        # based on keyword overlap to simulate memory recall pathways visually.
        doc_keywords = {}
        for d in doc_rows:
            txt = (d['content'] or '').lower()
            if 'python' in txt: doc_keywords['python'] = f"doc_{d['id']}"
            if 'api' in txt: doc_keywords['api'] = f"doc_{d['id']}"
            if 'code' in txt: doc_keywords['code'] = f"doc_{d['id']}"
            
        for r in rows:
            txt = (str(r['user_message']) + " " + str(r['ai_response'])).lower()
            for kw, doc_id in doc_keywords.items():
                if kw in txt:
                    # Weak, thin, long-range semantic link across the graph!
                    edges.append({
                        "from": doc_id,
                        "to": f"conv_{r['id']}",
                        "thickness": 0.2, # Very thin
                        "type": "recall"
                    })

    except Exception as e:
        print("Error fetching graph data:", e)
    finally:
        conn.close()
        
    return {"nodes": nodes, "edges": edges}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)
