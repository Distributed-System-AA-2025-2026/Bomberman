class ServerReference:
    def __init__(self, address: str, port: int):
        self.address = address
        self.port = port

    def get_full_reference(self) -> str:
        return f"{self.address}:{self.port}"