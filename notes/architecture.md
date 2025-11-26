# Bomberman Project – Architecture

## 1. Objective and Basic Choices

We want to build a multiplayer Bomberman with:
- **Matchmaking via REST** (latency tolerant, easy to make idempotent).
- **Realtime via socket** (low latency, continuous flow of input/state).
- CAP Choice:
  - **AP-oriented hub (eventual consistency)**
  Each hub maintains room memberships and directories locally; dead nodes are removed after a local timeout, and information is propagated via gossip.
  - **CP-oriented room with “Best effort”** (single and consistent game state; global availability remains high by disconnecting unstable clients).

---

## 2. Main Components

### 2.1 Hub Servers (Matchmaking)
- Hub servers are **pure peers**.
Each hub makes decisions locally and replicates membership and rooms via epidemic gossip with a last-writer-wins (LWW) rule based on a timestamp/logical clock.
- Each hub maintains a table of known peers:
- `known_lobbies = {id, address, last_seen, status}`
- Each hub also maintains a local room directory, also replicated via gossip:
- `known_rooms = {room_id -> room_info, last_update, ...}`
- Membership is kept up-to-date with:
- Periodic heartbeats between hubs;
- Local timeout/expiry: If a peer is not seen by `T_expire`, it is marked as `DOWN` and removed locally;
- Gossip: Changes (JOIN/LEAVE/FAIL) are propagated to other hubs.
- A new hub server joins by contacting a seed specified at runtime, receives:
- peer list,
- snapshot of the room directory,
and immediately begins heartbeat/gossip.

### 2.2 Hub Peer Management
The initial server has no server to connect to and simply becomes the first node/seed of the cluster.

#### 2.2.1 Connecting a New Hub Server
The new node `N` connects to any node `X`. At this point, `X` sends all hub and room status (membership + room directory) to `N`.

From here on:

- `N` begins sending heartbeat/gossip to `X` and the other peers it has just learned.
- Each peer that sees `N` for the first time:
- adds it to `known_lobbies` with the status `JOINING/UP`;
- propagates the presence of `N` in the next gossip.

As soon as `N` enters the gossip, it is considered active by the other peers (possibly at different times, but with eventual convergence).

#### 2.2.2 Disconnecting a Hub Server
When a node (`X`) becomes unresponsive:

- Each hub that hasn't received a heartbeat from `X` for more than `T_expire`:
- Marks `X` as `DOWN` or removes it from `known_lobbies`;
- Includes this information in the next gossip.
- Over time, all peers participating in the gossip converge on the "`X` is dead" view.

### 2.3 Room Servers (Game)
- Each room server manages a room/game:
- Maintains the **authoritative state** (positions, bombs, explosions, power-ups, scores);
- Processes client input;
- Sends state snapshots/deltas to clients.

---

## 3. Matchmaking

### 3.1 Room Creation / Assignment
1. A client contacts a hub server `X` via REST requesting to play.
2. `X` checks for starting or open rooms it knows about locally (local room directory).
3. In best-effort mode, `X` can use:
- updated status via gossip;
- or ask some peers (e.g., one or a few) if they have any starting rooms.
The response is not synchronized across all nodes and may be partial, but is sufficient for the AP.
4. If a peer responds with an available room, `X` returns an access token to that room to the client.
5. If no peer has any starting rooms (as far as `X` knows at that time), `X` creates a new room locally:
- `X` generates a globally unique `room_id`;
- registers the room in its room directory as `PENDING/STARTING` with a `lease_TTL` (timestamp `last_update`);
- propagates the update via gossip to other hubs (LWW / eventual consistency);
- other hubs receiving the update begin seeing that room as "starting" and can assign it to clients.

If the room does not become active within the TTL (e.g., the game does not start, no clients join):
- `X` (and then the others, via gossip) marks the room as expired/closed (tombstone).

> In practice: the hub prioritizes **availability** and matchmaking speed.
> Each hub can continue to serve requests even in the presence of partitions, using its own local state and the state propagated via gossip.
> Accepted compromise: in rare cases, **more rooms than necessary** may be created (e.g., two hubs in different partitions each create a room); This is an accepted anomaly in AP and can be mitigated with cleanup policies (automatically closing empty or rarely used rooms).

### 3.2 REST Idempotence
- "Give me a room" requests are idempotent:
- the client includes a `request_id`;
- if it retries within a TTL, it receives **the same token** (as long as the associated room is still valid);

This prevents the creation of extra rooms just because the client has timed out.

---

## 4. Room Token

- Payload:
```json
{
"room_id": "...", //Room ID
"hub_id": "...", //Hub that generated the room
"issued_at": "...", //Creation date
"expires_at": "..." //Expiration date (follows the game start, if there are enough players)
}
```
---
## 5. Game realtime in the room (CP best effort)

### 5.1 Connection
1. The client opens a socket to the room server and presents the token.
2. The room server validates the token and adds the player to the room.
3. When the minimum number of players is reached, the room switches to "in game".

### 5.2 Tick-based Game Loop
- The room server operates on a fixed tick basis (10 or 20 ticks per second):
1. Collects inputs received in the current tick;
2. Sorts them using `seq_num` per client (or logical timestamp);
3. Updates the game state deterministically;
4. Sends deltas/snapshots of the state to clients.
- This makes the order of events independent of network latency.

### 5.3 Partition and Disconnect Management
- The room remains **CP**: the state is unique and is never forked across clients.
- If a client fails to communicate due to `T_disconnect`:
  - It is marked disconnected and removed from the loop;
- The game continues for the others (**Global best effort**).
- Rejoin (TO BE EVALUATED):
  - Optional but clarified in the project: rejoining is possible within `T_rejoin` by reusing the token or a new rejoin token; beyond the window, the player is considered out.

---

## 6. CAP Summary for the Report

- **Hub = AP (Eventual Consistency)**
Goal: Allow each hub to perform matchmaking even across network partitions, using local state and gossip (membership + room directory).
Accepted Tradeoff: Node views may temporarily diverge, and it is possible to create more rooms than necessary; the system converges over time thanks to gossip and cleanup policies.

- **Room = CP (A Best Effort)**
Goal: A single, consistent game state, essential for bomb placement, explosions, and collisions.
Accepted Tradeoff: Unstable clients are disconnected to avoid contaminating the state.

---