# Security Best Practices for JRVS

## Overview

This document outlines security considerations, vulnerabilities, and best practices for JRVS deployment and development.

## Security Principles

1. **Input Validation** - Validate all user inputs
2. **Output Encoding** - Encode outputs to prevent injection
3. **Resource Cleanup** - Prevent memory leaks and resource exhaustion
4. **Authentication** - Secure API endpoints when deployed
5. **Data Privacy** - Protect sensitive user data

## Known Security Considerations

### 1. SQL Injection Protection

**Status:** ✅ Protected

JRVS uses parameterized queries with aiosqlite:

```python
# GOOD - Parameterized query
await db.execute(
    "SELECT * FROM documents WHERE url = ?",
    (url,)
)

# BAD - String formatting (vulnerable)
await db.execute(
    f"SELECT * FROM documents WHERE url = '{url}'"
)
```

All database queries use parameterized statements.

### 2. Cross-Site Scripting (XSS)

**Status:** ⚠️ Requires attention in web interfaces

**Mitigation:**
- Sanitize HTML content when displaying in web UI
- Use Content Security Policy headers
- Encode user-generated content

```python
from html import escape

# Sanitize user input before display
safe_text = escape(user_input)
```

### 3. Command Injection

**Status:** ✅ Protected

MCP server commands use subprocess with array arguments:

```python
# GOOD - Array arguments
subprocess.run(["npx", "-y", package_name], ...)

# BAD - Shell string (vulnerable)
subprocess.run(f"npx -y {package_name}", shell=True)
```

### 4. Path Traversal

**Status:** ⚠️ Requires validation

When accepting file paths from users:

```python
import os
from pathlib import Path

def validate_path(user_path, allowed_dir):
    """Validate path is within allowed directory"""
    user_path = Path(user_path).resolve()
    allowed_dir = Path(allowed_dir).resolve()
    
    # Check if user_path is within allowed_dir
    try:
        user_path.relative_to(allowed_dir)
        return True
    except ValueError:
        return False
```

### 5. Denial of Service (DoS)

**Status:** ⚠️ Requires rate limiting

**Mitigation:**
- Implement rate limiting on API endpoints
- Set request size limits
- Use timeouts for all operations
- Limit concurrent connections

```python
from fastapi import FastAPI
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()

@app.post("/api/chat")
@limiter.limit("5/minute")
async def chat(request: Request):
    # Implementation
    pass
```

### 6. Memory Exhaustion

**Status:** ✅ Mitigated

Implemented resource cleanup:
- Embedding cache with size limits
- Document chunk size limits
- Connection pooling
- Proper async cleanup

```python
# Resource cleanup patterns
async with EmbeddingManager() as manager:
    await manager.encode_text(texts)
# Automatic cleanup on exit
```

### 7. Secrets Management

**Status:** ⚠️ Requires environment variables

**Best Practices:**
```python
import os
from dotenv import load_dotenv

# Load from environment
load_dotenv()

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY environment variable required")

# NEVER hardcode secrets
# BAD: API_KEY = "sk-1234567890abcdef"
```

### 8. HTTPS/TLS

**Status:** ⚠️ Required for production

Use reverse proxy (nginx/Caddy) for TLS:

```nginx
server {
    listen 443 ssl http2;
    server_name jrvs.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Security Checklist for Deployment

### Pre-Deployment

- [ ] Review all API endpoints for authentication
- [ ] Enable HTTPS/TLS for production
- [ ] Set up rate limiting
- [ ] Configure CORS properly
- [ ] Review file upload restrictions
- [ ] Enable security headers
- [ ] Set up logging and monitoring
- [ ] Review database permissions
- [ ] Validate all user inputs
- [ ] Test error handling (no info leakage)

### Configuration

```python
# api/server.py security headers
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=3600,
)

# Security headers
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response
```

### Monitoring

```python
# Log security events
import logging

security_logger = logging.getLogger("security")
security_logger.setLevel(logging.WARNING)

# Log suspicious activity
security_logger.warning(f"Failed login attempt from {ip}")
security_logger.warning(f"Rate limit exceeded for {user}")
```

## Vulnerability Scanning

### CodeQL Scanning

Run security scans before deployment:

```bash
# Using GitHub CodeQL
# Setup in .github/workflows/codeql.yml

# Manual scan
codeql database create jrvs-db --language=python
codeql database analyze jrvs-db --format=sarif-latest --output=results.sarif
```

### Dependency Scanning

```bash
# Check for vulnerable dependencies
pip install safety
safety check

# Or use GitHub Dependabot
# Configure in .github/dependabot.yml
```

## Secure Coding Guidelines

### 1. Input Validation

```python
from pydantic import BaseModel, validator

class ChatRequest(BaseModel):
    message: str
    session_id: str
    
    @validator('message')
    def validate_message(cls, v):
        if not v or len(v) > 10000:
            raise ValueError("Message must be 1-10000 characters")
        return v.strip()
```

### 2. Output Encoding

```python
from html import escape
from urllib.parse import quote

# HTML context
html_safe = escape(user_input)

# URL context
url_safe = quote(user_input)

# JSON context (automatically safe with json.dumps)
import json
json_safe = json.dumps(user_input)
```

### 3. Error Handling

```python
# Don't expose internal details
try:
    result = process_request(data)
except Exception as e:
    # Log full error internally
    logger.error(f"Error processing request: {e}", exc_info=True)
    
    # Return generic error to user
    return {"error": "An error occurred processing your request"}
    # DON'T: return {"error": str(e)}
```

### 4. Authentication Example

```python
from fastapi import Depends, HTTPException, Header
from typing import Optional

async def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")
    
    token = authorization.replace("Bearer ", "")
    
    # Verify token (implement your logic)
    if not is_valid_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return token

@app.post("/api/secure-endpoint")
async def secure_endpoint(token: str = Depends(verify_token)):
    # Only called if token is valid
    pass
```

### 5. Rate Limiting

```python
from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/chat")
@limiter.limit("10/minute")
async def chat(request: Request):
    pass
```

## Incident Response

### Security Incident Checklist

1. **Identify** the scope and impact
2. **Contain** the threat (disable affected services)
3. **Eradicate** the vulnerability
4. **Recover** services safely
5. **Review** and update security measures

### Logging Security Events

```python
import logging
from datetime import datetime

security_log = logging.getLogger("security")

def log_security_event(event_type, details, severity="WARNING"):
    security_log.log(
        getattr(logging, severity),
        f"[{datetime.now().isoformat()}] {event_type}: {details}"
    )

# Usage
log_security_event("FAILED_AUTH", f"IP: {ip}, User: {user}", "WARNING")
log_security_event("RATE_LIMIT", f"IP: {ip} exceeded limit", "INFO")
```

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [SQLite Security](https://www.sqlite.org/security.html)

## Reporting Security Issues

If you discover a security vulnerability, please email security@example.com with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

**Do not** open public GitHub issues for security vulnerabilities.
