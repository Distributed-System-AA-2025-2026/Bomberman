from enum import Enum

class RoomStatus(Enum):
    DORMANT = "dormant"      # Created but not accepting players
    ACTIVE = "active"        # Waiting for players
    PLAYING = "playing"      # Playing
    CLOSED = "closed"        # Ended. To be deleted