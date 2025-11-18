# Distributed Bomberman Project Guide - Notes

These are some ideas and notes to help us structure and implement the Bomberman project.

## Project Structure

```
bomberman-distributed/
├── .github/
│   └── workflows/
│       └── ci.yml                 # CI/CD pipeline
├── server/
│   ├── __init__.py
│   ├── game_state.py             # Game state management
│   ├── room_manager.py           # Room/matchmaking logic
│   ├── network/
│   │   ├── socket_server.py      # TCP socket handling
│   │   └── protocol.py           # Communication protocol
│   └── tests/
├── client/
│   ├── __init__.py
│   ├── game_client.py            # Client logic
│   ├── ui/
│   │   └── game_ui.py            # Frontend/UI
│   ├── network/
│   │   └── socket_client.py      # Client socket handling
│   └── tests/
├── shared/
│   ├── __init__.py
│   ├── models.py                 # Shared data models
│   └── constants.py              # Game constants
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
├── .gitignore
├── README.md
├── pyproject.toml                # Poetry configuration
└── requirements.txt              # Fallback dependencies
```

---

## Development Workflow (GitHub Flow)

For each feature:

1. **Create a new branch**: `feature/room-management`
2. **Make commits** with clear messages
3. **Write tests FIRST** (TDD approach)
4. **Implement the feature**
5. **Open a Pull Request**
6. **Review each other's code**
7. **Merge to main**

---

## Server Pseudocode

### Client Handler

```python
async def handle_client(reader, writer):
    register_player(...)
    try:
        while True:
            msg = await read_frame(reader)
            process_player_action(msg)
    finally:
        disconnect_player()
```

### Game Room Loop

```python
async def room_loop():
    tick = 0
    while room_running:
        process_pending_actions()
        update_game_state(dt)
        broadcast_state()
        tick += 1
        await asyncio.sleep(1.0 / TICK_RATE)
```

---

## Implementation Roadmap

### GitHub Repository Setup

- Initialize `README.md` with project title and team names
- Create `.gitignore` specific for Python:

---

### Technical Setup

#### Build System (Poetry)

Initialize the project with *poetry*. This handles dependencies and virtual environments.

**Dependencies to consider**:

- **Game Loop**: `pygame` (standard for Python 2D games)
- **Networking**: Native `asyncio` (built-in)
  - Best for high-concurrency servers
  - Avoid high-level wrappers like HTTP/Flask for game sockets
  - You need raw TCP speed
- **Testing**: `pytest`

#### Continuous Integration (CI)

Create `.github/workflows/python-app.yml`:

- Configure it to install Poetry
- Run `poetry run pytest` on every push to main branch
- 
---

### Architecture & Protocol Design

#### Define the Protocol

Since we want Consistency (C) in CAP, our protocol is critical. 
Definining messages structure (e.g., JSON or custom byte format):

**Example Messages**:
- `CONNECT`
- `MOVE(x, y)`
- `PLANT_BOMB`
- `GAME_STATE_UPDATE`

#### The "CP" Strategy

**Design Decision**: 
- When a client sends a move, they should strictly wait for the server to confirm the new coordinate before rendering the move
- Alternative: Use client-side prediction with strict rollback

**Partition Handling**: 
- Define the "Timeout" threshold
- If the server doesn't hear from a client in N seconds:
  - Option A: The game pauses for everyone (loading screen)
  - Option B: The player is dropped

---

## Commit Message Guidelines
- Use the imperative mood: "Add feature" not "Added feature"
- Prefix types:
  - `feat:` A new feature
  - `fix:` A bug fix
  - `docs:` Documentation only changes
  - `refactor:` Code changes that neither fixes a bug nor adds a feature
  - `test:` Adding missing tests or correcting existing tests
  - `chore:` Changes to the build process or auxiliary tools and libraries such as documentation generation
- Examples:
  - `feat: implement room management`
  - `fix: correct player movement logic`
  - `docs: update README with setup instructions`
  - `refactor: simplify game state update logic`
  - `test: add tests for network protocol handling`
  - `chore: update CI configuration`