"""
Extract topics from conversation history using LLM + embeddings
"""

import asyncio
import json
import re
from typing import List, Dict, Optional
from datetime import datetime

from llm.ollama_client import ollama_client
from rag.embeddings import embedding_manager
from memory_map.database import mindmap_db


class TopicExtractor:
    """Extract and categorize topics from conversations"""
    
    # Valid categories for topic classification
    CATEGORIES = ['programming', 'research', 'personal', 'work', 'learning', 'other']
    
    def __init__(self):
        self.db = mindmap_db
        
    async def initialize(self):
        """Initialize the topic extractor"""
        await self.db.initialize()
        await embedding_manager.initialize()

    async def extract_topics_from_conversation(
        self, 
        conversation_id: int,
        conversation_text: str
    ) -> List[Dict]:
        """
        Use LLM to extract main topics from a conversation
        
        Args:
            conversation_id: The ID of the conversation
            conversation_text: The full text of the conversation
            
        Returns:
            List of topic dictionaries with topic, category, and relevance
        """
        
        # Limit context to prevent token overflow
        text_chunk = conversation_text[:3000] if len(conversation_text) > 3000 else conversation_text
        
        prompt = f"""Analyze this conversation and extract the main topics discussed.
Return ONLY a valid JSON array of topics with categories and relevance scores.
Do not include any explanation or additional text outside the JSON.

Conversation:
{text_chunk}

Categories to use: programming, research, personal, work, learning, other

Return format (JSON array only):
[
    {{"topic": "specific topic name", "category": "category", "relevance": 0.8}}
]

Rules:
- Extract 1-5 main topics
- Topic names should be specific but concise (2-5 words)
- Relevance is 0.0 to 1.0 (how central is this topic to the conversation)
- Use only the categories listed above

JSON array:"""
        
        try:
            response = await ollama_client.generate(
                prompt=prompt,
                stream=False
            )
            
            if not response:
                return []
            
            topics = self._parse_topics_json(response)
            
            # Generate embeddings for each topic
            for topic in topics:
                try:
                    embeddings = await embedding_manager.encode_text(topic['topic'])
                    topic['embedding'] = embeddings[0] if len(embeddings) > 0 else None
                except Exception as e:
                    print(f"Error generating embedding for topic: {e}")
                    topic['embedding'] = None
                
            return topics
            
        except Exception as e:
            print(f"Error extracting topics: {e}")
            return []

    def _parse_topics_json(self, llm_response: str) -> List[Dict]:
        """
        Parse LLM response to extract topic JSON
        """
        try:
            # Clean up the response - remove any markdown code blocks
            cleaned = llm_response.strip()
            cleaned = re.sub(r'^```json\s*', '', cleaned)
            cleaned = re.sub(r'^```\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            
            # Try to find JSON array in the response
            json_match = re.search(r'\[\s*\{.*?\}\s*\]', cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group(0)
            
            topics = json.loads(cleaned)
            
            if not isinstance(topics, list):
                return []
            
            # Validate and normalize topics
            validated_topics = []
            for topic in topics:
                if isinstance(topic, dict) and 'topic' in topic:
                    validated_topic = {
                        'topic': str(topic['topic']).strip(),
                        'category': self._normalize_category(topic.get('category', 'other')),
                        'relevance': min(1.0, max(0.0, float(topic.get('relevance', 0.5))))
                    }
                    if validated_topic['topic']:  # Only add non-empty topics
                        validated_topics.append(validated_topic)
            
            return validated_topics[:5]  # Limit to 5 topics
            
        except json.JSONDecodeError:
            print(f"Failed to parse topics JSON from: {llm_response[:200]}")
            return []
        except Exception as e:
            print(f"Error parsing topics: {e}")
            return []

    def _normalize_category(self, category: str) -> str:
        """Normalize category to valid values"""
        category = str(category).lower().strip()
        if category in self.CATEGORIES:
            return category
        
        # Try to map common variations
        category_map = {
            'code': 'programming',
            'coding': 'programming',
            'development': 'programming',
            'dev': 'programming',
            'study': 'learning',
            'education': 'learning',
            'job': 'work',
            'career': 'work',
            'life': 'personal',
            'science': 'research',
            'analysis': 'research'
        }
        
        return category_map.get(category, 'other')

    async def batch_extract_from_history(self, limit: int = 100, 
                                         process_all: bool = False) -> Dict:
        """
        Process conversation history and extract all topics
        
        Args:
            limit: Maximum number of conversations to process
            process_all: If True, process all conversations; if False, only unprocessed ones
            
        Returns:
            Statistics about the extraction
        """
        await self.initialize()
        
        # Get conversations to process
        if process_all:
            conversations = await self.db.get_recent_conversations(limit)
        else:
            conversations = await self.db.get_unprocessed_conversations(limit)
        
        if not conversations:
            return {
                'status': 'complete',
                'processed': 0,
                'topics_extracted': 0,
                'message': 'No new conversations to process'
            }
        
        total_topics = 0
        processed = 0
        
        for conv in conversations:
            try:
                topics = await self.extract_topics_from_conversation(
                    conv['id'], 
                    conv['text']
                )
                
                for topic_data in topics:
                    await self._store_topic(conv['id'], topic_data)
                    total_topics += 1
                
                processed += 1
                
                # Add a small delay to avoid overwhelming the LLM
                if processed % 5 == 0:
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                print(f"Error processing conversation {conv['id']}: {e}")
                continue
        
        return {
            'status': 'complete',
            'processed': processed,
            'topics_extracted': total_topics,
            'message': f'Processed {processed} conversations, extracted {total_topics} topics'
        }

    async def _store_topic(self, conversation_id: int, topic_data: Dict):
        """
        Store topic in database and link to conversation
        """
        # Insert or update topic
        topic_id = await self.db.insert_or_update_topic(topic_data)
        
        # Link conversation to topic
        await self.db.link_conversation_topic(
            conversation_id, 
            topic_id, 
            topic_data.get('relevance', 0.5)
        )

    async def extract_topics_from_text(self, text: str) -> List[Dict]:
        """
        Extract topics from arbitrary text (not necessarily a conversation)
        Useful for analyzing documents or notes.
        """
        return await self.extract_topics_from_conversation(0, text)


# Global topic extractor instance
topic_extractor = TopicExtractor()
