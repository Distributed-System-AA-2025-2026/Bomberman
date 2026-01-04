"""
Unit tests for ServerReference class.
"""
import pytest
from bomberman.common.ServerReference import ServerReference

class TestServerReference:
    """Essential test suite for ServerReference class."""

    @pytest.mark.parametrize("address,port,expected", [
        # IPv4
        ("192.168.1.100", 8080, "192.168.1.100:8080"),
        ("192.168.1.1", 8080, "192.168.1.1:8080"),
        # IPv6
        ("::1", 8080, "::1:8080"),
        ("::1", 5000, "::1:5000"),
        # Domain names (Dummy)
        ("www.romanellas.cloud", 80, "www.romanellas.cloud:80"),
        # Domain names (Kubernetes)
        ("hub-server-0.hub-service.default.svc.cluster.local", 8080,
         "hub-server-0.hub-service.default.svc.cluster.local:8080"),
        ("hub-0.svc", 6000, "hub-0.svc:6000"),
        # Localhost
        ("localhost", 3000, "localhost:3000"),
    ])
    def test_server_reference(self, address, port, expected):
        """Test ServerReference with various address types."""
        ref = ServerReference(address, port)
        assert ref.address == address
        assert ref.port == port
        assert ref.get_full_reference() == expected