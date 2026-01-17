from datetime import datetime
from typing import Literal

def print_console(message: str, category: Literal['Error', 'Gossip', 'Info', 'FailureDetector', 'Error', 'Warning', 'RoomHandling'] = 'Gossip'):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}][HubServer][{category}]: {message}")