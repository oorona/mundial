"""
Tests for the Security Module
=============================

Tests the network validation, trusted request detection,
and security utilities.
"""

import pytest
from unittest.mock import MagicMock, patch
from app.core.security import (
    is_internal_ip,
    is_trusted_request,
    get_client_info,
    GATEWAY_HEADER,
    DOCKER_INTERNAL_NETWORKS,
)


class TestIsInternalIP:
    """Test IP address validation for internal networks."""
    
    def test_docker_bridge_network_172(self):
        """Docker bridge networks in 172.16-31.x.x are internal."""
        assert is_internal_ip("172.17.0.1") is True
        assert is_internal_ip("172.17.0.100") is True
        assert is_internal_ip("172.18.0.1") is True
        assert is_internal_ip("172.31.255.255") is True
    
    def test_docker_network_192_168(self):
        """192.168.x.x networks are internal."""
        assert is_internal_ip("192.168.1.1") is True
        assert is_internal_ip("192.168.0.100") is True
    
    def test_private_network_10(self):
        """10.x.x.x private networks are internal."""
        assert is_internal_ip("10.0.0.1") is True
        assert is_internal_ip("10.255.255.255") is True
    
    def test_localhost(self):
        """Localhost addresses are internal."""
        assert is_internal_ip("127.0.0.1") is True
        assert is_internal_ip("127.0.0.100") is True
    
    def test_public_ips_not_internal(self):
        """Public IP addresses are NOT internal."""
        assert is_internal_ip("8.8.8.8") is False
        assert is_internal_ip("1.1.1.1") is False
        assert is_internal_ip("203.0.113.1") is False
        assert is_internal_ip("98.76.54.32") is False
    
    def test_invalid_ip_not_internal(self):
        """Invalid IP strings are not internal."""
        assert is_internal_ip("not-an-ip") is False
        assert is_internal_ip("") is False
        assert is_internal_ip("256.256.256.256") is False


class TestIsTrustedRequest:
    """Test trusted request detection."""
    
    def _mock_request(
        self,
        client_ip: str = "192.168.1.1",
        gateway_header: bool = False,
        real_ip: str = None,
        forwarded_for: str = None,
    ) -> MagicMock:
        """Create a mock request with specified properties."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = client_ip
        request.url = MagicMock()
        request.url.path = "/api/v1/gemini/test"
        request.method = "GET"
        
        # Use a MagicMock for headers that supports .get()
        headers_dict = {
            "User-Agent": "Test Client",
        }
        if gateway_header:
            headers_dict[GATEWAY_HEADER] = "true"
        if real_ip:
            headers_dict["X-Real-IP"] = real_ip
        if forwarded_for:
            headers_dict["X-Forwarded-For"] = forwarded_for
        
        # Mock the headers object with a get method
        request.headers = MagicMock()
        request.headers.get = lambda k, d=None: headers_dict.get(k, d)
        
        return request
    
    def test_request_with_gateway_header_is_trusted(self):
        """Requests with X-Gateway-Request header are trusted."""
        request = self._mock_request(
            client_ip="1.2.3.4",  # External IP
            gateway_header=True
        )
        assert is_trusted_request(request) is True
    
    def test_request_from_internal_ip_is_trusted(self):
        """Requests from internal IPs are trusted."""
        request = self._mock_request(client_ip="172.17.0.1")
        assert is_trusted_request(request) is True
    
    def test_request_with_internal_x_real_ip_is_trusted(self):
        """Requests with internal X-Real-IP are trusted."""
        request = self._mock_request(
            client_ip="8.8.8.8",  # External
            real_ip="172.17.0.1"  # Internal
        )
        assert is_trusted_request(request) is True
    
    def test_request_with_internal_forwarded_for_is_trusted(self):
        """Requests with internal X-Forwarded-For are trusted."""
        request = self._mock_request(
            client_ip="8.8.8.8",
            forwarded_for="172.17.0.1, 8.8.8.8"
        )
        assert is_trusted_request(request) is True
    
    def test_request_from_external_ip_not_trusted(self):
        """Requests from external IPs without gateway header are NOT trusted."""
        request = self._mock_request(
            client_ip="203.0.113.50",
            gateway_header=False
        )
        assert is_trusted_request(request) is False
    
    def test_localhost_request_is_trusted(self):
        """Requests from localhost are trusted (development)."""
        request = self._mock_request(client_ip="127.0.0.1")
        assert is_trusted_request(request) is True


class TestGetClientInfo:
    """Test client info extraction for logging."""
    
    def test_extracts_client_info(self):
        """Should extract all relevant client info."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "172.17.0.1"
        request.url = MagicMock()
        request.url.path = "/api/v1/gemini/test"
        request.method = "POST"
        
        headers_dict = {
            "X-Real-IP": "192.168.1.1",
            "X-Forwarded-For": "10.0.0.1, 192.168.1.1",
            "User-Agent": "Mozilla/5.0 Test",
            GATEWAY_HEADER: "true",
        }
        request.headers = MagicMock()
        request.headers.get = lambda k, d=None: headers_dict.get(k, d)
        
        info = get_client_info(request)
        
        assert info["client_ip"] == "172.17.0.1"
        assert info["real_ip"] == "192.168.1.1"
        assert info["forwarded_for"] == "10.0.0.1, 192.168.1.1"
        assert info["has_gateway_header"] is True
        assert info["path"] == "/api/v1/gemini/test"
        assert info["method"] == "POST"
    
    def test_handles_missing_client(self):
        """Should handle missing client gracefully."""
        request = MagicMock()
        request.client = None
        request.url = MagicMock()
        request.url.path = "/test"
        request.method = "GET"
        
        headers_dict = {}
        request.headers = MagicMock()
        request.headers.get = lambda k, d=None: headers_dict.get(k, d)
        
        info = get_client_info(request)
        
        assert info["client_ip"] == "unknown"


class TestDockerNetworkConfiguration:
    """Verify the Docker network configuration is correct."""
    
    def test_docker_internal_networks_configured(self):
        """Should have the standard Docker internal network ranges."""
        network_strs = [str(n) for n in DOCKER_INTERNAL_NETWORKS]
        
        assert "172.16.0.0/12" in network_strs
        assert "192.168.0.0/16" in network_strs
        assert "10.0.0.0/8" in network_strs
        assert "127.0.0.0/8" in network_strs
    
    def test_gateway_header_name(self):
        """Verify the gateway header name matches nginx config."""
        assert GATEWAY_HEADER == "X-Gateway-Request"
