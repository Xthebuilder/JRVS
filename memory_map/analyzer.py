"""
Analyze mind map patterns and generate insights using LLM
"""

import json
from typing import List, Dict, Optional
from datetime import datetime

from llm.ollama_client import ollama_client
from memory_map.database import mindmap_db


class MindMapAnalyzer:
    """Analyze conversation patterns and generate insights"""
    
    # Icons for different insight types
    INSIGHT_ICONS = {
        "focus": "🎯",
        "pattern": "🔍",
        "learning": "📚",
        "cluster": "🗂️",
        "recommendation": "💡",
        "trend": "📈",
        "connection": "🔗",
        "gap": "⚠️",
        "strength": "💪",
        "default": "📌"
    }
    
    def __init__(self):
        self.db = mindmap_db
    
    async def initialize(self):
        """Initialize the analyzer"""
        await self.db.initialize()
    
    async def generate_insights(self, max_insights: int = 5) -> List[Dict]:
        """
        Use LLM to analyze conversation patterns and generate insights
        
        Args:
            max_insights: Maximum number of insights to generate
            
        Returns:
            List of insight dictionaries
        """
        await self.initialize()
        
        # Get graph statistics
        stats = await self.db.get_graph_statistics()
        
        if stats['total_topics'] == 0:
            return [{
                "type": "Info",
                "description": "No topics have been extracted yet. Use '/mindmap build' to analyze your conversation history.",
                "icon": "ℹ️",
                "style": "yellow"
            }]
        
        # Get top topics
        topics = await self.db.get_all_topics(limit=20)
        
        # Get category distribution
        category_counts = {}
        for topic in topics:
            cat = topic.get('category', 'other')
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        # Get recent relationships
        relationships = await self.db.get_topic_relationships(min_strength=0.5)
        
        # Build analysis prompt
        prompt = f"""Analyze this conversation pattern data and provide exactly {max_insights} interesting insights.

Statistics:
- Total topics discussed: {stats['total_topics']}
- Total connections between topics: {stats['total_connections']}
- Most discussed category: {stats['top_category']}
- Average mentions per topic: {stats['avg_mentions']}
- Conversations analyzed: {stats['conversations_processed']}

Category distribution: {json.dumps(category_counts)}

Top 15 topics (by mentions):
{json.dumps([{'name': t['topic_name'], 'category': t['category'], 'mentions': t['mention_count']} for t in topics[:15]], indent=2)}

Strong topic connections:
{json.dumps([{'topics': [r['topic_1_name'], r['topic_2_name']], 'strength': round(r['strength'], 2)} for r in relationships[:10]], indent=2)}

Provide exactly {max_insights} insights about:
1. Main areas of focus and expertise
2. Knowledge patterns and interests
3. Learning progression over time
4. Topic clustering and connections
5. Recommendations for exploration

Format each insight as a JSON array with this structure:
[
    {{"type": "Focus|Pattern|Learning|Cluster|Recommendation|Trend|Connection|Gap|Strength", "description": "The insight description"}}
]

JSON array only, no other text:"""

        try:
            response = await ollama_client.generate(
                prompt=prompt,
                stream=False
            )
            
            if not response:
                return self._get_fallback_insights(stats, topics, category_counts)
            
            insights = self._parse_insights(response)
            
            if not insights:
                return self._get_fallback_insights(stats, topics, category_counts)
            
            return insights[:max_insights]
            
        except Exception as e:
            print(f"Error generating insights: {e}")
            return self._get_fallback_insights(stats, topics, category_counts)
    
    def _parse_insights(self, llm_response: str) -> List[Dict]:
        """Parse LLM insights into structured format"""
        import re
        
        try:
            # Clean up the response
            cleaned = llm_response.strip()
            cleaned = re.sub(r'^```json\s*', '', cleaned)
            cleaned = re.sub(r'^```\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            
            # Try to find JSON array
            json_match = re.search(r'\[\s*\{.*?\}\s*(?:,\s*\{.*?\}\s*)*\]', cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group(0)
            
            raw_insights = json.loads(cleaned)
            
            if not isinstance(raw_insights, list):
                return []
            
            insights = []
            for item in raw_insights:
                if isinstance(item, dict) and 'type' in item and 'description' in item:
                    insight_type = str(item['type']).strip()
                    insights.append({
                        "type": insight_type,
                        "description": str(item['description']).strip(),
                        "icon": self._get_icon(insight_type),
                        "style": "cyan"
                    })
            
            return insights
            
        except json.JSONDecodeError:
            print(f"Failed to parse insights JSON")
            return []
        except Exception as e:
            print(f"Error parsing insights: {e}")
            return []
    
    def _get_icon(self, insight_type: str) -> str:
        """Get icon for insight type"""
        type_lower = insight_type.lower()
        return self.INSIGHT_ICONS.get(type_lower, self.INSIGHT_ICONS['default'])
    
    def _get_fallback_insights(self, stats: Dict, topics: List[Dict], 
                               category_counts: Dict) -> List[Dict]:
        """Generate basic insights without LLM if it fails"""
        insights = []
        
        # Focus insight
        if stats['top_category']:
            insights.append({
                "type": "Focus",
                "description": f"Your conversations are primarily focused on {stats['top_category']} topics ({stats['total_topics']} total topics tracked).",
                "icon": "🎯",
                "style": "cyan"
            })
        
        # Pattern insight
        if topics:
            top_topic = topics[0]
            insights.append({
                "type": "Pattern",
                "description": f"'{top_topic['topic_name']}' is your most discussed topic with {top_topic['mention_count']} mentions.",
                "icon": "🔍",
                "style": "cyan"
            })
        
        # Connection insight
        if stats['total_connections'] > 0:
            avg_connections = stats['total_connections'] / max(stats['total_topics'], 1)
            insights.append({
                "type": "Connection",
                "description": f"Your topics have an average of {avg_connections:.1f} connections each, showing how your knowledge areas interrelate.",
                "icon": "🔗",
                "style": "cyan"
            })
        
        # Category breakdown
        if category_counts:
            sorted_cats = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            cat_summary = ", ".join([f"{cat}: {count}" for cat, count in sorted_cats[:3]])
            insights.append({
                "type": "Cluster",
                "description": f"Topic distribution: {cat_summary}",
                "icon": "🗂️",
                "style": "cyan"
            })
        
        # Recommendation
        low_count_topics = [t for t in topics if t['mention_count'] == 1]
        if low_count_topics:
            insights.append({
                "type": "Recommendation",
                "description": f"You have {len(low_count_topics)} topics mentioned only once. Consider diving deeper into '{low_count_topics[0]['topic_name']}' to strengthen that knowledge area.",
                "icon": "💡",
                "style": "cyan"
            })
        
        return insights

    async def get_topic_timeline(self, topic_id: int) -> List[Dict]:
        """
        Get the timeline of when a topic was discussed
        
        Args:
            topic_id: The topic to get timeline for
            
        Returns:
            List of conversation dates with the topic
        """
        await self.initialize()
        
        conversations = await self.db.get_conversations_for_topic(topic_id, limit=50)
        
        timeline = []
        for conv in conversations:
            timeline.append({
                'date': conv['date'],
                'summary': conv['summary'],
                'relevance': conv['relevance']
            })
        
        return timeline

    async def get_knowledge_gaps(self) -> List[Dict]:
        """
        Identify potential knowledge gaps - topics with few connections
        
        Returns:
            List of topics that might benefit from more exploration
        """
        await self.initialize()
        
        # Get all topics
        topics = await self.db.get_all_topics(limit=100)
        
        gaps = []
        for topic in topics:
            related = await self.db.get_related_topics(topic['id'], limit=5)
            
            # Topics with few connections might be knowledge gaps
            if len(related) < 2 and topic['mention_count'] > 1:
                gaps.append({
                    'topic': topic['topic_name'],
                    'category': topic['category'],
                    'mentions': topic['mention_count'],
                    'connections': len(related),
                    'suggestion': f"Consider exploring how '{topic['topic_name']}' relates to other topics you've discussed."
                })
        
        return sorted(gaps, key=lambda x: x['mentions'], reverse=True)[:10]


# Global analyzer instance
mindmap_analyzer = MindMapAnalyzer()
