# Distributed Bomberman

## Abstract

This project implements a distributed, real-time Bomberman game designed for multiplayer gameplay with a focus on scalability and fault tolerance. Developed for the **Distributed Systems Course A.Y. 2025/2026** at the University of Bologna.

The architecture is split into two distinct layers:

* **Hub Layer (AP-oriented):** Responsible for matchmaking and cluster coordination.
* **Room Layer (CP-oriented):** Executes the authoritative game loop using deterministic ticks over TCP.

## Architecture

### 1. The Hub Server (`bomberman/hub_server`)

The entry point for all clients. It is designed to be horizontally scalable and partition-tolerant.

* **Discovery:** Uses a **Gossip Protocol** to disseminate room availability and peer liveness without a centralized database.
* **Matchmaking:** Handles client requests via REST API to find available game rooms.
* **Failure Detection:** Monitors the health of registered Room Servers.

### 2. The Room Server (`bomberman/room_server`)

The authoritative game engine.

* **Game Loop:** Runs a strict, deterministic tick loop.
* **Communication:** Uses **TCP sockets** with **Protocol Buffers** for low-latency, reliable state synchronization.
* **Persistence:** Snapshotting mechanisms to handle transient failures.

### 3. The Client (`Client.py`)

A thin, protocol-driven client that renders the game state via a retro-style **ASCII interface**.

---

## Getting Started

### Prerequisites

* **Python**
* **Poetry**
* **Docker**
* **Kubernetes Cluster** 
* **kubectl**

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/Distributed-System-AA-2025-2026/Bomberman
cd bomberman
```

2. **Install Python Dependencies:**
```bash
poetry install
```

---

## Deployment

The project includes a complete Kubernetes setup for orchestrating the Hub and Room servers.

### Local Kubernetes Deployment

We provide utility scripts to streamline local deployment.

1. **Build and Deploy:**
Navigate to the scripts directory and run the deployment script.
```bash
cd k8s/scripts
./deploy-local.sh
```

*This script builds the Docker images (`Dockerfile.hub`, `Dockerfile.room`) and applies the manifests in `k8s/base/`.*

2. **Check Status:**
```bash
./status.sh
```

3. **Cleanup:**
To tear down the cluster resources:
```bash
./cleanup.sh
```

---

## How to Play

Once the infrastructure is running:

1. **Start the Client:**
```bash
poetry run python Client.py
```

2. **Controls:**
* `WASD` or Arrow Keys: Move
* `SPACE`: Place Bomb
* `Q`: Quit

---

## Testing

The project employs a tiered testing strategy using `pytest`.

### Running Tests

To run the full suite:

```bash
poetry run pytest
```

### Test Structure

* **Unit Tests** (`tests/unit`): Isolate individual components.
* **Integration Tests** (`tests/integration`): Test interaction between modules.
* **End-to-End Tests** (`tests/e2e`): Simulate full game scenarios.

---

## Project Structure

```text
.
├── bomberman/
│   ├── common/           # Shared logic
│   ├── hub_server/       # Matchmaking, Gossip Protocol, Failure Detection
│   └── room_server/      # Game Engine, Physics, TCP handling
├── docker/               # Dockerfiles for Hub and Room
├── k8s/                  # Kubernetes manifests
│   └── scripts/          # Helper scripts
├── notes/                # Documentation and diagrams
├── tests/                # Unit, Integration, and E2E tests
├── Client.py             # The player client
└── pyproject.toml        # Poetry configuration
```