"""
Build relationship graph between topics
"""

import numpy as np
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from memory_map.database import mindmap_db


class TopicGraphBuilder:
    """Builds and manages the topic relationship graph"""
    
    def __init__(self):
        self.db = mindmap_db
    
    async def initialize(self):
        """Initialize the graph builder"""
        await self.db.initialize()
    
    async def build_topic_graph(self, 
                                time_range: str = "all",
                                category: Optional[str] = None,
                                min_connections: int = 0,
                                min_strength: float = 0.3) -> Dict:
        """
        Create graph structure from topics and relationships
        
        Args:
            time_range: Filter by time - "all", "week", "month", "year"
            category: Filter by category
            min_connections: Minimum connections for a topic to be included
            min_strength: Minimum relationship strength to show edge
            
        Returns:
            Graph structure with nodes and edges
        """
        await self.initialize()
        
        # Get all topics
        topics = await self.db.get_all_topics(limit=200)
        
        if not topics:
            return {
                "nodes": [],
                "edges": [],
                "metadata": {
                    "total_topics": 0,
                    "total_connections": 0,
                    "generated_at": datetime.now().isoformat()
                }
            }
        
        # Calculate relationships if not already done
        await self._calculate_topic_relationships(topics)
        
        # Get relationships from database
        relationships = await self.db.get_topic_relationships(min_strength)
        
        # Build nodes list
        nodes = []
        node_ids = set()
        
        for topic in topics:
            # Apply category filter
            if category and topic['category'] != category:
                continue
                
            # Apply time filter
            if time_range != "all":
                if not self._topic_in_time_range(topic, time_range):
                    continue
            
            node = {
                "id": topic['id'],
                "label": topic['topic_name'],
                "size": topic['mention_count'],
                "category": topic['category'] or 'other',
                "first_seen": topic['first_mentioned'],
                "last_seen": topic['last_mentioned']
            }
            nodes.append(node)
            node_ids.add(topic['id'])
        
        # Build edges list (only for nodes that exist in our filtered set)
        edges = []
        for rel in relationships:
            if rel['topic_id_1'] in node_ids and rel['topic_id_2'] in node_ids:
                edges.append({
                    "source": rel['topic_id_1'],
                    "target": rel['topic_id_2'],
                    "weight": rel['strength'],
                    "type": rel.get('relationship_type', 'related')
                })
        
        # Filter nodes by minimum connections if specified
        if min_connections > 0:
            # Count connections per node
            connection_count = {}
            for edge in edges:
                connection_count[edge['source']] = connection_count.get(edge['source'], 0) + 1
                connection_count[edge['target']] = connection_count.get(edge['target'], 0) + 1
            
            # Filter nodes
            filtered_node_ids = {
                node['id'] for node in nodes 
                if connection_count.get(node['id'], 0) >= min_connections
            }
            nodes = [n for n in nodes if n['id'] in filtered_node_ids]
            edges = [e for e in edges if e['source'] in filtered_node_ids and e['target'] in filtered_node_ids]
        
        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "total_topics": len(nodes),
                "total_connections": len(edges),
                "generated_at": datetime.now().isoformat(),
                "filters": {
                    "time_range": time_range,
                    "category": category,
                    "min_connections": min_connections
                }
            }
        }
    
    def _topic_in_time_range(self, topic: Dict, time_range: str) -> bool:
        """Check if topic was mentioned within the specified time range"""
        last_mentioned = topic.get('last_mentioned')
        if not last_mentioned:
            return True  # Include topics without timestamp
        
        try:
            if isinstance(last_mentioned, str):
                last_dt = datetime.fromisoformat(last_mentioned.replace('Z', '+00:00'))
            else:
                last_dt = last_mentioned
            
            now = datetime.now()
            
            if time_range == "week":
                cutoff = now - timedelta(days=7)
            elif time_range == "month":
                cutoff = now - timedelta(days=30)
            elif time_range == "year":
                cutoff = now - timedelta(days=365)
            else:
                return True
            
            # Make cutoff timezone-naive for comparison
            if hasattr(cutoff, 'tzinfo') and cutoff.tzinfo is not None:
                cutoff = cutoff.replace(tzinfo=None)
            if hasattr(last_dt, 'tzinfo') and last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)
                
            return last_dt >= cutoff
            
        except Exception as e:
            print(f"Error parsing timestamp: {e}")
            return True
    
    async def _calculate_topic_relationships(self, topics: List[Dict]):
        """
        Calculate relationships between topics based on:
        1. Co-occurrence in conversations
        2. Embedding similarity
        3. Category matching
        """
        
        # Only process topics that have embeddings
        topics_with_embeddings = [t for t in topics if t.get('embedding')]
        
        for i, topic1 in enumerate(topics):
            for topic2 in topics[i+1:]:
                # Calculate relationship strength
                strength, rel_type = await self._calculate_relationship_strength(
                    topic1, 
                    topic2
                )
                
                if strength > 0.3:  # Threshold for showing connection
                    await self.db.store_topic_relationship(
                        topic1['id'], 
                        topic2['id'], 
                        strength,
                        rel_type
                    )
    
    async def _calculate_relationship_strength(
        self, 
        topic1: Dict, 
        topic2: Dict
    ) -> tuple:
        """
        Combine multiple signals to determine relationship strength
        
        Returns:
            Tuple of (strength, relationship_type)
        """
        
        # 1. Co-occurrence score (how often mentioned together)
        co_occurrence = await self.db.get_topic_co_occurrence(
            topic1['id'], 
            topic2['id']
        )
        co_occurrence_score = min(co_occurrence / 5.0, 1.0)  # Normalize, cap at 5 co-occurrences
        
        # 2. Semantic similarity (embedding distance)
        similarity_score = 0.0
        if topic1.get('embedding') and topic2.get('embedding'):
            try:
                embedding1 = np.frombuffer(topic1['embedding'], dtype=np.float32)
                embedding2 = np.frombuffer(topic2['embedding'], dtype=np.float32)
                
                # Cosine similarity
                dot_product = np.dot(embedding1, embedding2)
                norm1 = np.linalg.norm(embedding1)
                norm2 = np.linalg.norm(embedding2)
                
                if norm1 > 0 and norm2 > 0:
                    similarity_score = float(dot_product / (norm1 * norm2))
                    similarity_score = max(0, similarity_score)  # Ensure non-negative
            except Exception as e:
                print(f"Error calculating embedding similarity: {e}")
        
        # 3. Category matching
        category_score = 1.0 if topic1.get('category') == topic2.get('category') else 0.0
        
        # 4. Temporal proximity (discussed in similar time periods)
        temporal_score = 0.0
        try:
            last1 = topic1.get('last_mentioned')
            last2 = topic2.get('last_mentioned')
            
            if last1 and last2:
                if isinstance(last1, str):
                    last1 = datetime.fromisoformat(last1.replace('Z', '+00:00'))
                if isinstance(last2, str):
                    last2 = datetime.fromisoformat(last2.replace('Z', '+00:00'))
                
                # Make timezone-naive for comparison
                if hasattr(last1, 'tzinfo') and last1.tzinfo:
                    last1 = last1.replace(tzinfo=None)
                if hasattr(last2, 'tzinfo') and last2.tzinfo:
                    last2 = last2.replace(tzinfo=None)
                    
                time_diff = abs((last1 - last2).days)
                temporal_score = 1.0 / (1.0 + time_diff / 7.0)  # Decay over weeks
        except Exception as e:
            print(f"Error calculating temporal proximity: {e}")
        
        # Weighted combination
        strength = (
            0.4 * co_occurrence_score +
            0.3 * similarity_score +
            0.1 * category_score +
            0.2 * temporal_score
        )
        
        # Determine relationship type
        if category_score > 0:
            rel_type = "same_category"
        elif co_occurrence_score > 0.5:
            rel_type = "co_discussed"
        elif similarity_score > 0.7:
            rel_type = "semantically_similar"
        else:
            rel_type = "related"
        
        return float(strength), rel_type

    async def get_topic_cluster(self, topic_id: int, depth: int = 2) -> Dict:
        """
        Get a cluster of topics around a central topic
        
        Args:
            topic_id: The central topic ID
            depth: How many levels of related topics to include
            
        Returns:
            Graph with the topic and its related topics
        """
        await self.initialize()
        
        visited = set()
        nodes = []
        edges = []
        
        async def explore_topic(tid: int, current_depth: int):
            if tid in visited or current_depth > depth:
                return
            
            visited.add(tid)
            
            topic = await self.db.get_topic_by_id(tid)
            if not topic:
                return
            
            nodes.append({
                "id": topic['id'],
                "label": topic['topic_name'],
                "size": topic['mention_count'],
                "category": topic['category'] or 'other',
                "depth": current_depth  # Distance from central topic
            })
            
            related = await self.db.get_related_topics(tid, limit=10)
            
            for rel in related:
                if rel['id'] not in visited:
                    edges.append({
                        "source": tid,
                        "target": rel['id'],
                        "weight": rel['strength']
                    })
                    await explore_topic(rel['id'], current_depth + 1)
        
        await explore_topic(topic_id, 0)
        
        return {
            "nodes": nodes,
            "edges": edges,
            "central_topic_id": topic_id,
            "depth": depth
        }


# Global graph builder instance
graph_builder = TopicGraphBuilder()
