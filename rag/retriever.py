"""RAG retriever that coordinates embeddings, vector search, and context building"""
import asyncio
from typing import List, Dict, Optional, Tuple
import time
import re

from config import MAX_CONTEXT_LENGTH, MAX_RETRIEVED_CHUNKS, CHUNK_SIZE, CHUNK_OVERLAP, TIMEOUTS
from .vector_store import vector_store
from .embeddings import embedding_manager
from core.database import db

class RAGRetriever:
    def __init__(self):
        self.initialized = False

    async def initialize(self):
        """Initialize all RAG components"""
        if self.initialized:
            return
        
        await db.initialize()
        await vector_store.initialize()
        await embedding_manager.initialize()
        
        self.initialized = True

    async def add_document(self, content: str, title: str = "", url: str = "", 
                          metadata: Dict = None) -> int:
        """Add a document to the RAG system"""
        await self.initialize()
        
        if metadata is None:
            metadata = {}
        
        # Store document in database
        document_id = await db.add_document(
            url=url,
            title=title,
            content=content,
            content_type='text',
            metadata=metadata
        )
        
        # Chunk the document
        chunks = self._chunk_text(content)
        
        # Store chunks in database
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            chunk_id = await db.add_document_chunk(
                document_id=document_id,
                chunk_text=chunk,
                chunk_index=i
            )
            chunk_ids.append(chunk_id)
        
        # Add chunks to vector store
        chunk_metadata = [
            {
                'document_id': document_id,
                'chunk_index': i,
                'chunk_id': chunk_ids[i],
                'title': title,
                'url': url
            }
            for i in range(len(chunks))
        ]
        
        await vector_store.add_chunks(chunks, document_id, chunk_metadata)
        
        print(f"Added document '{title}' with {len(chunks)} chunks")
        return document_id

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        # Simple sentence-aware chunking
        sentences = re.split(r'[.!?]+', text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Check if adding this sentence would exceed chunk size
            if len(current_chunk) + len(sentence) + 1 > CHUNK_SIZE:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    
                    # Start new chunk with overlap
                    words = current_chunk.split()
                    if len(words) > CHUNK_OVERLAP:
                        overlap_text = ' '.join(words[-CHUNK_OVERLAP:])
                        current_chunk = overlap_text + ' ' + sentence
                    else:
                        current_chunk = sentence
                else:
                    # Single sentence is too long, split by words
                    words = sentence.split()
                    for i in range(0, len(words), CHUNK_SIZE // 10):
                        word_chunk = ' '.join(words[i:i + CHUNK_SIZE // 10])
                        chunks.append(word_chunk)
                    current_chunk = ""
            else:
                current_chunk += ' ' + sentence if current_chunk else sentence
        
        # Add remaining chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return [chunk for chunk in chunks if chunk.strip()]

    async def retrieve_context(self, query: str, session_id: str = None) -> str:
        """Retrieve relevant context for a query"""
        await self.initialize()
        
        start_time = time.time()
        
        try:
            # Get relevant chunks from vector search
            search_results = await vector_store.search(
                query=query,
                k=MAX_RETRIEVED_CHUNKS
            )
            
            # Get recent conversation context if session provided
            conversation_context = ""
            if session_id:
                recent_conversations = await db.get_recent_conversations(
                    session_id=session_id,
                    limit=3
                )
                if recent_conversations:
                    conversation_context = self._format_conversation_context(recent_conversations)
            
            # Build context from search results
            document_context = self._format_document_context(search_results)
            
            # Combine contexts
            full_context = ""
            if conversation_context:
                full_context += f"Recent conversation:\n{conversation_context}\n\n"
            
            if document_context:
                full_context += f"Relevant information:\n{document_context}"
            
            # Trim context to max length
            if len(full_context) > MAX_CONTEXT_LENGTH:
                full_context = full_context[:MAX_CONTEXT_LENGTH] + "..."
            
            elapsed = time.time() - start_time
            if elapsed > TIMEOUTS["context_building"]:
                print(f"Warning: Context building took {elapsed:.2f}s")
            
            return full_context
            
        except Exception as e:
            print(f"Error retrieving context: {e}")
            return ""

    def _format_conversation_context(self, conversations: List[Dict]) -> str:
        """Format recent conversations into context"""
        context_parts = []
        
        for conv in reversed(conversations[-3:]):  # Last 3 conversations
            user_msg = conv['user_message'][:200] + "..." if len(conv['user_message']) > 200 else conv['user_message']
            ai_resp = conv['ai_response'][:300] + "..." if len(conv['ai_response']) > 300 else conv['ai_response']
            
            context_parts.append(f"User: {user_msg}")
            context_parts.append(f"Assistant: {ai_resp}")
        
        return '\n'.join(context_parts)

    def _format_document_context(self, search_results: List[Tuple[str, float, Dict]]) -> str:
        """Format search results into context"""
        if not search_results:
            return ""
        
        context_parts = []
        seen_documents = set()
        
        for text, similarity, metadata in search_results:
            # Avoid duplicate content from same document
            doc_key = (metadata.get('document_id'), metadata.get('chunk_index', 0))
            if doc_key in seen_documents:
                continue
            seen_documents.add(doc_key)
            
            # Format context piece
            title = metadata.get('title', 'Document')
            url = metadata.get('url', '')
            
            context_piece = f"[{title}]"
            if url:
                context_piece += f" ({url})"
            context_piece += f":\n{text.strip()}"
            
            context_parts.append(context_piece)
        
        return '\n\n'.join(context_parts)

    async def search_documents(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for documents by content"""
        await self.initialize()
        
        # Try vector search first
        search_results = await vector_store.search(query, k=limit)
        
        if search_results:
            # Group by document and return document info
            doc_results = {}
            for text, similarity, metadata in search_results:
                doc_id = metadata.get('document_id')
                if doc_id and doc_id not in doc_results:
                    doc_results[doc_id] = {
                        'document_id': doc_id,
                        'title': metadata.get('title', 'Untitled'),
                        'url': metadata.get('url', ''),
                        'similarity': similarity,
                        'preview': text[:200] + "..." if len(text) > 200 else text
                    }
            
            return list(doc_results.values())
        
        # Fallback to database text search
        db_results = await db.get_documents_by_query(query, limit)
        return [
            {
                'document_id': doc['id'],
                'title': doc['title'],
                'url': doc['url'],
                'similarity': 0.0,
                'preview': doc['content'][:200] + "..." if len(doc['content']) > 200 else doc['content']
            }
            for doc in db_results
        ]

    async def get_stats(self) -> Dict:
        """Get RAG system statistics"""
        await self.initialize()
        
        vector_stats = await vector_store.get_stats()
        
        return {
            'vector_store': vector_stats,
            'embedding_cache_size': embedding_manager.get_cache_size(),
            'embedding_dimension': embedding_manager.get_embedding_dimension()
        }

    async def cleanup(self):
        """Cleanup RAG resources"""
        await vector_store.cleanup()

# Global RAG retriever instance
rag_retriever = RAGRetriever()