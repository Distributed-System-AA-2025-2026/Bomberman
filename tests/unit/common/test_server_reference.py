import pytest
from bomberman.common.ServerReference import ServerReference


class TestServerReference:

    def test_get_full_reference_formats_correctly(self):
        ref = ServerReference("192.168.1.1", 8080)
        assert ref.get_full_reference() == "192.168.1.1:8080"

    def test_get_full_reference_with_hostname(self):
        ref = ServerReference("hub-0.service.local", 9000)
        assert ref.get_full_reference() == "hub-0.service.local:9000"

    def test_equality_same_address_and_port(self):
        ref1 = ServerReference("10.0.0.1", 5000)
        ref2 = ServerReference("10.0.0.1", 5000)
        assert ref1 == ref2

    def test_inequality_different_address(self):
        ref1 = ServerReference("10.0.0.1", 5000)
        ref2 = ServerReference("10.0.0.2", 5000)
        assert ref1 != ref2

    def test_inequality_different_port(self):
        ref1 = ServerReference("10.0.0.1", 5000)
        ref2 = ServerReference("10.0.0.1", 5001)
        assert ref1 != ref2

    @pytest.mark.parametrize("address,port,expected", [
        ("localhost", 0, "localhost:0"),
        ("0.0.0.0", 65535, "0.0.0.0:65535"),
        ("", 80, ":80"),
    ])
    def test_get_full_reference_edge_cases(self, address, port, expected):
        assert ServerReference(address, port).get_full_reference() == expected

    def test_eq_crashes_on_non_server_reference(self):
        ref = ServerReference("10.0.0.1", 5000)
        result = (ref == "not_a_server_reference")
        assert result is False


    def test_eq_crashes_on_none(self):
        ref = ServerReference("10.0.0.1", 5000)
        result = (ref == None)
        assert result is False