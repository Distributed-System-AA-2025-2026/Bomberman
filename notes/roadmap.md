# Bomberman Server Development Tasks

## Networking Layer on Server 

* Implement TCP framing protocol (length-prefixed)
* Integrate protobuf/msgpack serialization
* Manage concurrent clients (async)
* Error-handling, keep-alive, disconnect detection
  
## Core Room Server (Authoritative Engine)

* Implement core game model (grid, players, bombs, explosions)
* Implement authoritative tick-loop (asyncio-based)
* Implement action queue + validation (server-side anti-cheat)
* Implement state diffs & broadcast logic
* Handle join/leave, reconnection timeouts
* Implement consistency under partial failures
* Write unit tests for:
   * movement rules
   * bomb timers
   * explosion propagation
   * collision rules

## Match Lifecycle Management (Server-Side)

* Room created on-demand
* Room destruction when empty
* Clean shutdown & final state emission
* Reconnection grace period handling
* Post-match cleanup

## Testing, CI, Performance

* Write integration tests with simulated clients
* Add pytest-asyncio tests
* Load testing (simulate 20–50 clients)
* Ensure deterministic tests for game logic
* GitHub Actions integration (lint + test)

## Dockerization & Kubernetes

* Dockerfile for Room Server
* Kubernetes Deployment for room server template
* Networking config (services, environment injection)
* Automate room-server pod creation strategy (template or static scaling)
* Add docs & scripts for deploying locally (minikube/kind)