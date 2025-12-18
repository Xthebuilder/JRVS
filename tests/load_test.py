#!/usr/bin/env python3
"""
Load testing script for JRVS API using Locust

Usage:
    locust -f tests/load_test.py --host=http://localhost:8080
    
Then open http://localhost:8089 in your browser to start the load test.
"""

from locust import HttpUser, task, between
import random


class JRVSApiUser(HttpUser):
    """
    Simulates a user interacting with the JRVS API
    """
    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks
    
    def on_start(self):
        """Called when a user starts"""
        self.session_id = f"load_test_session_{random.randint(1, 1000)}"
    
    @task(3)
    def chat_endpoint(self):
        """Test the chat endpoint - most common operation"""
        payload = {
            "message": f"Test message {random.randint(1, 100)}",
            "session_id": self.session_id
        }
        
        with self.client.post("/api/chat", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def search_endpoint(self):
        """Test the search endpoint"""
        queries = ["Python", "machine learning", "web development", "AI", "programming"]
        query = random.choice(queries)
        
        with self.client.get(f"/api/search?q={query}", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def models_endpoint(self):
        """Test the models endpoint"""
        with self.client.get("/api/models", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def stats_endpoint(self):
        """Test the stats endpoint"""
        with self.client.get("/api/stats", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")


class JRVSRagUser(HttpUser):
    """
    Simulates a user performing RAG operations
    """
    wait_time = between(2, 5)
    
    @task(2)
    def retrieve_context(self):
        """Test context retrieval - RAG heavy operation"""
        queries = [
            "How does machine learning work?",
            "What is Python used for?",
            "Explain neural networks",
            "Best practices for web development"
        ]
        
        payload = {
            "query": random.choice(queries)
        }
        
        with self.client.post("/api/rag/retrieve", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def add_document(self):
        """Test document addition"""
        payload = {
            "content": f"Load test document {random.randint(1, 10000)}. This is test content for load testing purposes.",
            "title": f"Load Test Doc {random.randint(1, 1000)}",
            "url": f"https://example.com/loadtest/{random.randint(1, 1000)}"
        }
        
        with self.client.post("/api/rag/document", json=payload, catch_response=True) as response:
            if response.status_code in [200, 201]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")


class JRVSStressUser(HttpUser):
    """
    Heavy stress testing user - makes rapid concurrent requests
    """
    wait_time = between(0.1, 0.5)
    
    @task
    def rapid_fire_requests(self):
        """Make rapid requests to stress test the system"""
        endpoints = [
            "/api/models",
            "/api/stats",
            "/api/health"
        ]
        
        endpoint = random.choice(endpoints)
        
        with self.client.get(endpoint, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")


# Example test scenarios
"""
Light load:
    locust -f tests/load_test.py --users 10 --spawn-rate 1 --host=http://localhost:8080

Medium load:
    locust -f tests/load_test.py --users 50 --spawn-rate 5 --host=http://localhost:8080

Heavy load:
    locust -f tests/load_test.py --users 200 --spawn-rate 10 --host=http://localhost:8080

Stress test (headless):
    locust -f tests/load_test.py --users 500 --spawn-rate 50 --host=http://localhost:8080 --headless --run-time 5m
"""
