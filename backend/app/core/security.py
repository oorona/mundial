"""
Security Module
===============

Provides security utilities and middleware for the backend API:

- Network validation (ensure requests come from trusted sources)
- Request origin verification
- Security logging
- Defense-in-depth measures for sensitive endpoints

**Architecture:**
The backend is NOT directly exposed to the internet. All external traffic
flows through the nginx gateway on the intranet. The network topology:

  Internet -> Gateway (nginx:80) -> Backend (intranet:8000)
                    |
  Frontend (Next.js) -> Backend (intranet:8000)
                    |
  Bot (Discord) -----> Backend (intranet:8000)

**Trusted Sources:**
- Gateway requests: Have X-Gateway-Request header
- Frontend SSR: Originates from frontend container
- Bot requests: Uses Bot token authentication
- Internal services: Docker intranet IPs (172.x.x.x)

**Security Layers:**
1. Network isolation (Docker networks)
2. Gateway rate limiting (nginx)
3. Backend rate limiting (slowapi)
4. Authentication (session/JWT)
5. This middleware (request validation)
"""

import ipaddress
import os
from typing import Optional, Callable
from functools import wraps

from fastapi import Request, HTTPException, status
import structlog

logger = structlog.get_logger()

# ============================================================================
# Trusted Network Configuration
# ============================================================================

# Docker internal networks (typically 172.16-31.x.x and 192.168.x.x)
DOCKER_INTERNAL_NETWORKS = [
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),  # Localhost
]

# Gateway header that nginx sets for proxied requests
GATEWAY_HEADER = "X-Gateway-Request"

# Trusted service hostnames (resolved within Docker network)
TRUSTED_HOSTNAMES = ["frontend", "bot", "gateway", "backend", "localhost"]


def is_internal_ip(ip_str: str) -> bool:
    """Check if an IP address is from a trusted internal network."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in DOCKER_INTERNAL_NETWORKS)
    except ValueError:
        return False


def is_trusted_request(request: Request) -> bool:
    """
    Determine if a request comes from a trusted source.
    
    A request is trusted if it:
    1. Has the X-Gateway-Request header (came through nginx gateway)
    2. Originates from an internal Docker network IP
    3. Is from localhost (development)
    """
    # Check for gateway header
    if request.headers.get(GATEWAY_HEADER):
        return True
    
    # Get client IP (may be forwarded)
    client_ip = request.client.host if request.client else None
    real_ip = request.headers.get("X-Real-IP", client_ip)
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    
    # Check if any IP is internal
    ips_to_check = [ip for ip in [client_ip, real_ip, forwarded_for] if ip]
    
    for ip in ips_to_check:
        if is_internal_ip(ip):
            return True
    
    return False


def get_client_info(request: Request) -> dict:
    """Extract client information for logging."""
    return {
        "client_ip": request.client.host if request.client else "unknown",
        "real_ip": request.headers.get("X-Real-IP"),
        "forwarded_for": request.headers.get("X-Forwarded-For"),
        "user_agent": request.headers.get("User-Agent", "")[:100],
        "has_gateway_header": bool(request.headers.get(GATEWAY_HEADER)),
        "path": request.url.path,
        "method": request.method,
    }


# ============================================================================
# Security Decorators for Endpoints
# ============================================================================

def require_internal_network(func: Callable) -> Callable:
    """
    Decorator to restrict endpoint access to internal network only.
    
    Use for extremely sensitive endpoints that should never be
    accessible from external sources, even with authentication.
    
    Usage:
        @router.post("/dangerous-operation")
        @require_internal_network
        async def dangerous_operation(request: Request):
            ...
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        if not is_trusted_request(request):
            client_info = get_client_info(request)
            logger.warning(
                "blocked_external_access_attempt",
                endpoint=request.url.path,
                **client_info
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint is not accessible from external networks"
            )
        return await func(request, *args, **kwargs)
    
    return wrapper


def log_security_event(event_type: str, request: Request, **extra):
    """Log a security-related event."""
    client_info = get_client_info(request)
    logger.info(
        f"security_event_{event_type}",
        **client_info,
        **extra
    )


# ============================================================================
# Rate Limit Helpers
# ============================================================================

def get_rate_limit_key(request: Request) -> str:
    """
    Generate a rate limit key for the request.
    
    Uses X-Real-IP if available (behind proxy), otherwise client IP.
    Includes endpoint path for more granular limiting.
    """
    real_ip = request.headers.get("X-Real-IP")
    client_ip = request.client.host if request.client else "unknown"
    ip = real_ip or client_ip
    
    return f"{ip}:{request.url.path}"


# ============================================================================
# Security Headers Validation
# ============================================================================

REQUIRED_SECURITY_HEADERS_FOR_MUTATIONS = ["Content-Type"]

def validate_mutation_request(request: Request) -> None:
    """
    Validate that mutation requests (POST, PUT, DELETE, PATCH)
    have required security headers.
    """
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        content_type = request.headers.get("Content-Type", "")
        if not content_type:
            logger.warning(
                "missing_content_type",
                path=request.url.path,
                method=request.method
            )


# ============================================================================
# Environment-Specific Security
# ============================================================================

def is_development() -> bool:
    """Check if running in development mode."""
    return os.getenv("ENVIRONMENT", "development").lower() in ["dev", "development", "local"]


def is_production() -> bool:
    """Check if running in production mode."""
    return os.getenv("ENVIRONMENT", "development").lower() in ["prod", "production"]


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "is_internal_ip",
    "is_trusted_request",
    "get_client_info",
    "require_internal_network",
    "log_security_event",
    "get_rate_limit_key",
    "validate_mutation_request",
    "is_development",
    "is_production",
    "DOCKER_INTERNAL_NETWORKS",
    "GATEWAY_HEADER",
    "TRUSTED_HOSTNAMES",
]
