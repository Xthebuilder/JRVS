"""
Load testing for JRVS API using Locust
Tests the performance of chat, RAG retrieval, and document ingestion endpoints
"""
from locust import HttpUser, task, between
import json
import random


class JRVSUser(HttpUser):
    """Simulated user for load testing JRVS API"""
    
    # Wait between 1-3 seconds between tasks
    wait_time = between(1, 3)
    
    # Test data
    test_queries = [
        "What is Python?",
        "Explain machine learning",
        "How does RAG work?",
        "Tell me about artificial intelligence",
        "What are neural networks?",
        "Explain natural language processing",
        "What is deep learning?",
        "How do transformers work?",
        "What is the difference between AI and ML?",
        "Explain vector databases"
    ]
    
    test_urls = [
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "https://en.wikipedia.org/wiki/Machine_learning",
        "https://en.wikipedia.org/wiki/Artificial_intelligence"
    ]
    
    def on_start(self):
        """Called when a simulated user starts"""
        self.session_id = f"load_test_session_{random.randint(1000, 9999)}"
        print(f"Starting user with session: {self.session_id}")
    
    @task(5)  # Weight: 5x more frequent than other tasks
    def chat_query(self):
        """Test chat endpoint with random queries"""
        query = random.choice(self.test_queries)
        
        payload = {
            "message": query,
            "session_id": self.session_id,
            "stream": False
        }
        
        with self.client.post(
            "/api/chat",
            json=payload,
            catch_response=True,
            name="POST /api/chat"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(2)
    def search_documents(self):
        """Test document search endpoint"""
        query = random.choice(self.test_queries)
        
        with self.client.get(
            f"/api/search?query={query}",
            catch_response=True,
            name="GET /api/search"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def scrape_url(self):
        """Test web scraping endpoint (less frequent due to resource usage)"""
        url = random.choice(self.test_urls)
        
        payload = {"url": url}
        
        with self.client.post(
            "/api/scrape",
            json=payload,
            catch_response=True,
            name="POST /api/scrape"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(3)
    def get_models(self):
        """Test models listing endpoint"""
        with self.client.get(
            "/api/models",
            catch_response=True,
            name="GET /api/models"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(2)
    def health_check(self):
        """Test health endpoint"""
        with self.client.get(
            "/health",
            catch_response=True,
            name="GET /health"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def get_history(self):
        """Test conversation history endpoint"""
        with self.client.get(
            f"/api/history/{self.session_id}",
            catch_response=True,
            name="GET /api/history"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")


class IntenseUser(HttpUser):
    """High-intensity user for stress testing"""
    
    wait_time = between(0.1, 0.5)  # Rapid requests
    
    @task
    def rapid_chat(self):
        """Rapid-fire chat requests"""
        payload = {
            "message": "Quick test",
            "stream": False
        }
        
        self.client.post("/api/chat", json=payload)


class RAGFocusedUser(HttpUser):
    """User focused on RAG operations"""
    
    wait_time = between(1, 2)
    
    @task(5)
    def search_intensive(self):
        """Intensive search operations"""
        queries = [
            "Python", "JavaScript", "TypeScript", "Rust", "Go",
            "React", "Vue", "Angular", "Django", "Flask"
        ]
        
        for query in random.sample(queries, 3):
            self.client.get(f"/api/search?query={query}")
    
    @task(1)
    def context_retrieval(self):
        """Test RAG context retrieval"""
        payload = {
            "message": "Explain this concept in detail with examples",
            "stream": False
        }
        
        self.client.post("/api/chat", json=payload)


# To run load tests:
# 1. Start JRVS API server: python api/server.py
# 2. Run locust: locust -f tests/load_test.py --host=http://localhost:8000
# 3. Open browser: http://localhost:8089
# 4. Configure users and spawn rate
#
# Example command line usage:
# locust -f tests/load_test.py --host=http://localhost:8000 --users 10 --spawn-rate 1 --run-time 5m --headless
