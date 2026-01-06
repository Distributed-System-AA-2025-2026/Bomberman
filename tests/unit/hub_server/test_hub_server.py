# test_hub_server.py
import pytest
from hub_server.HubServer import get_hub_index


class TestGetHubIndex:
    """Test suite for get_hub_index function"""

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-1.local", 1),
        ("hub-34.local", 34),
        ("hub-542.hub-headless.default.svc.cluster.local", 542),
        ("hub-1000.local", 1000),
        ("hub-20930.hub-headless.default.svc.cluster.local", 20930),
    ])
    def test_valid_indices_different_magnitudes(self, hostname: str, expected: int):
        """Test parsing of hub indices across different orders of magnitude"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-0.local", 0),
        ("hub-0.hub-headless.default.svc.cluster.local", 0),
    ])
    def test_index_zero(self, hostname: str, expected: int):
        """Test that index 0 is correctly parsed (edge case: first pod)"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-007.local", 7),
        ("hub-0042.local", 42),
    ])
    def test_leading_zeros(self, hostname: str, expected: int):
        """Test that leading zeros are handled correctly"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-99999999.local", 99999999),
        ("hub-123456789.hub-headless.default.svc.cluster.local", 123456789),
    ])
    def test_large_indices(self, hostname: str, expected: int):
        """Test parsing of very large indices"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname", [
        "",                          # empty string
        "hub-.local",                # missing index
        "hub.local",                 # missing dash and index
        "server-0.local",            # wrong prefix
        "HUB-0.local",               # wrong case
        "hub-abc.local",             # letters instead of digits
        "hub-12abc.local",           # mixed digits and letters
        "hub--1.local",              # double dash (negative-like)
        "0-hub.local",               # reversed format
        "  hub-0.local",             # leading whitespace
        "hub-0.local  ",             # trailing whitespace (re.match handles this, but let's be explicit)
    ])
    def test_invalid_hostname_raises_value_error(self, hostname: str):
        """Test that invalid hostnames raise ValueError"""
        with pytest.raises(ValueError, match="Invalid hub hostname"):
            get_hub_index(hostname)

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-5", 5),                           # no domain
        ("hub-123.a.b.c.d.e.f.g", 123),         # deeply nested domain
    ])
    def test_various_domain_formats(self, hostname: str, expected: int):
        """Test that domain suffix doesn't affect parsing"""
        assert get_hub_index(hostname) == expected