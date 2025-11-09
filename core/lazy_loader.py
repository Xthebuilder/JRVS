"""Lazy loading manager for efficient resource usage"""
import asyncio
import weakref
from typing import Any, Callable, Dict, Optional, TypeVar, Generic
import time
from functools import wraps
import threading

T = TypeVar('T')

class LazyLoader(Generic[T]):
    """Generic lazy loader for any resource"""
    
    def __init__(self, loader_func: Callable[[], T], ttl: Optional[float] = None):
        self.loader_func = loader_func
        self.ttl = ttl  # Time to live in seconds
        self._resource = None
        self._loaded_at = None
        self._loading = False
        self._lock = asyncio.Lock()

    async def get(self) -> T:
        """Get the resource, loading if necessary"""
        async with self._lock:
            # Check if resource is expired
            if self._should_reload():
                await self._load()
            
            return self._resource

    def _should_reload(self) -> bool:
        """Check if resource should be reloaded"""
        if self._resource is None:
            return True
        
        if self.ttl and self._loaded_at:
            return time.time() - self._loaded_at > self.ttl
        
        return False

    async def _load(self):
        """Load the resource"""
        if self._loading:
            return
        
        self._loading = True
        try:
            # Run loader in thread pool if it's a sync function
            if asyncio.iscoroutinefunction(self.loader_func):
                self._resource = await self.loader_func()
            else:
                loop = asyncio.get_event_loop()
                self._resource = await loop.run_in_executor(None, self.loader_func)
            
            self._loaded_at = time.time()
        finally:
            self._loading = False

    def invalidate(self):
        """Invalidate the cached resource"""
        self._resource = None
        self._loaded_at = None

class ResourcePool:
    """Pool for managing reusable resources"""
    
    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self._pool = {}
        self._usage_count = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, key: str, factory: Callable) -> Any:
        """Get resource from pool or create new one"""
        async with self._lock:
            if key in self._pool:
                self._usage_count[key] = self._usage_count.get(key, 0) + 1
                return self._pool[key]
            
            # Create new resource
            if asyncio.iscoroutinefunction(factory):
                resource = await factory()
            else:
                loop = asyncio.get_event_loop()
                resource = await loop.run_in_executor(None, factory)
            
            # Add to pool (with eviction if needed)
            if len(self._pool) >= self.max_size:
                await self._evict_lru()
            
            self._pool[key] = resource
            self._usage_count[key] = 1
            
            return resource

    async def _evict_lru(self):
        """Evict least recently used resource"""
        if not self._pool:
            return
        
        # Find LRU resource
        lru_key = min(self._usage_count, key=self._usage_count.get)
        
        # Clean up resource if it has cleanup method
        resource = self._pool[lru_key]
        if hasattr(resource, 'cleanup'):
            try:
                if asyncio.iscoroutinefunction(resource.cleanup):
                    await resource.cleanup()
                else:
                    resource.cleanup()
            except Exception as e:
                print(f"Error cleaning up resource {lru_key}: {e}")
        
        # Remove from pool
        del self._pool[lru_key]
        del self._usage_count[lru_key]

    async def cleanup_all(self):
        """Clean up all resources in pool"""
        async with self._lock:
            for key, resource in self._pool.items():
                if hasattr(resource, 'cleanup'):
                    try:
                        if asyncio.iscoroutinefunction(resource.cleanup):
                            await resource.cleanup()
                        else:
                            resource.cleanup()
                    except Exception as e:
                        print(f"Error cleaning up resource {key}: {e}")
            
            self._pool.clear()
            self._usage_count.clear()

class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs):
        """Call function with circuit breaker protection"""
        async with self._lock:
            if self.state == "OPEN":
                if self._should_attempt_reset():
                    self.state = "HALF_OPEN"
                else:
                    raise Exception("Circuit breaker is OPEN")
            
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
                
                # Success - reset circuit breaker
                if self.state == "HALF_OPEN":
                    self.state = "CLOSED"
                    self.failure_count = 0
                
                return result
                
            except Exception as e:
                self.failure_count += 1
                self.last_failure_time = time.time()
                
                if self.failure_count >= self.failure_threshold:
                    self.state = "OPEN"
                
                raise e

    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt reset"""
        if self.last_failure_time is None:
            return True
        
        return time.time() - self.last_failure_time > self.recovery_timeout

def with_timeout(timeout_seconds: float):
    """Decorator to add timeout to async functions"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                raise Exception(f"Function {func.__name__} timed out after {timeout_seconds} seconds")
        return wrapper
    return decorator

def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator to retry function on failure"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        print(f"Attempt {attempt + 1} failed: {e}. Retrying in {current_delay}s...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        print(f"All {max_retries + 1} attempts failed")
            
            raise last_exception
        return wrapper
    return decorator

class HealthChecker:
    """Health monitoring for system components"""
    
    def __init__(self):
        self.components = {}
        self.health_status = {}
        self._running = False
        self._check_interval = 30  # seconds

    def register_component(self, name: str, health_check_func: Callable):
        """Register a component for health monitoring"""
        self.components[name] = health_check_func
        self.health_status[name] = {"status": "unknown", "last_check": None, "error": None}

    async def start_monitoring(self):
        """Start health monitoring loop"""
        self._running = True
        
        while self._running:
            await self._check_all_components()
            await asyncio.sleep(self._check_interval)

    async def stop_monitoring(self):
        """Stop health monitoring"""
        self._running = False

    async def _check_all_components(self):
        """Check health of all registered components"""
        for name, check_func in self.components.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    is_healthy = await check_func()
                else:
                    loop = asyncio.get_event_loop()
                    is_healthy = await loop.run_in_executor(None, check_func)
                
                self.health_status[name] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                    "last_check": time.time(),
                    "error": None
                }
                
            except Exception as e:
                self.health_status[name] = {
                    "status": "error",
                    "last_check": time.time(),
                    "error": str(e)
                }

    def get_health_status(self) -> Dict[str, Dict]:
        """Get current health status of all components"""
        return self.health_status.copy()

    def is_system_healthy(self) -> bool:
        """Check if overall system is healthy"""
        return all(
            status["status"] == "healthy" 
            for status in self.health_status.values()
        )

# Global instances
resource_pool = ResourcePool()
health_checker = HealthChecker()