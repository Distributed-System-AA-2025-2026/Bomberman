class ServerReference:
    def __init__(self, address: str, port: int):
        self.address = address
        self.port = port

    def get_full_reference(self) -> str:
        return f"{self.address}:{self.port}"

    def __eq__(self, other):
        if other.__class__ != ServerReference:
            return False
        return self.address == other.address and self.port == other.port