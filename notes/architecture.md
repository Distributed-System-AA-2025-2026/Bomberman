# Progetto Bomberman – Architettura

## 1. Obiettivo e scelte di base

Vogliamo realizzare un Bomberman multiplayer con:
- **Matchmaking via REST** (tollerante a latenze, facile da rendere idempotente).
- **Realtime via socket** (bassa latenza, flusso continuo di input/stato).
- Scelta CAP:
  - **Lobby orientata a CP** (I membri rimuovono i nodi morti se entro X secondi questi non rispondono - implica la presenza di nodo di bootstrapping condiviso).
  - **Stanza orientata a CP con “A best effort”** (stato di gioco unico e consistente; la disponibilità globale resta alta disconnettendo client instabili).

---

## 2. Componenti principali

### 2.1 Lobby servers (matchmaking)
- I lobby server sono peer ma usano un leader attivo per serializzare membership; il leader può cambiare con elezione, se il leader precedente muore.
- Ogni lobby mantiene una tabella dei peer noti:
  - `known_lobbies = {id, address, last_seen}`
- La membership è tenuta aggiornata con:
  - **heartbeat periodici** tra lobby;
  - **timeout/expiry**: se un peer non è visto da `T_expire`, viene rimosso.
- Un nuovo lobby server entra contattando un **seed** indicato a runtime, riceve lista peer (da nodo bootstrap) e inizia heartbeat/gossip leggero.

### 2.2 Gestione peers lobby
Il server iniziale non ha un server a cui collegarsi e diventa il leader dei lobby.
#### 2.2.1 Connessione di un nuovo server lobby
Il nuovo nodo `N` si collega a un nodo qualunque `X`. A questo punto `X` invia a `N` tutto lo stato delle lobby. (Soprattutto i peers).

`N` comunica la sua presenza al leader (`L`) che lo autentica (se la votazione di almeno `N/2` host è favorevole), va tutto a buon file, allora `L` comunica che `N` esiste e fornisce il suo `IP` (o hostname in k8s) con la porta. Finchè il leader non lo autentica `N` è in uno stato readonly.

#### 2.2.2 Disconnessione di un server lobby (non leader)
Quando un nodo (`X`) non risponde più, allora il leader comunica a tutti che il nodo `X` è caduto, anche qui previa votazione, quindi si procede alla sua rimozione dalla lista di nodi  

#### 2.2.3 Disconnessione di un server lobby (leader)
Quando il leader `L` non risponde più, allora, essendo la lista di nodi ordinata su ogni peer, si inizia a comunicare col secondo nodo, che diventa il leader (previa votazione di tutti gli altri host - Servono almeno `N/2` host), quindi il nuovo leader `L'` comunica la rimozione di `L`.

Il timeout per ogni nodo (leader e non) deve essere specificato.  


### 2.3 Room servers (partita)
- Ogni room server gestisce una stanza/partita:
  - mantiene lo **stato authoritative** (posizioni, bombe, esplosioni, power–up, punteggi);
  - processa input dei client;
  - invia ai client snapshot/delta di stato.

---

## 3. Matchmaking

### 3.1 Creazione / assegnazione stanza
1. Un client contatta un lobby server `X` via REST chiedendo di giocare.
2. `X` controlla le stanze **in avvio** che conosce localmente.
3. Se non ne ha, chiede ai peer vivi se hanno stanze in avvio.
4. Se un peer risponde con una stanza disponibile, `X` restituisce al client un **token di accesso** a quella stanza.
5. Se nessun peer ha stanze in avvio, `X` crea una nuova stanza evitando gare con gli altri lobby tramite **claim con lease**:
   - `X` genera `room_id`;
   - annuncia ai peer: “sto creando `room_id`” con TTL (`lease_TTL`); (devono accettare la creazione della nuova stanza - richiede comunque `N/2` host )
   - finché la lease è valida, gli altri lobby considerano la stanza “in avvio” e non ne creano una concorrente per lo stesso slot di matchmaking;
   - se la stanza non diventa attiva entro TTL, l’annuncio scade automaticamente.

> In pratica: la lobby privilegia disponibilità e velocità di matchmaking. In caso di partizione, solo il gruppo che mantiene quorum può creare nuove stanze; i nodi in minoranza rifiutano matchmaking (A best effort).

### 3.2 Idempotenza REST
- Le richieste “dammi una stanza” sono idempotenti:
  - il client include un `request_id`;
  - se ritenta entro un TTL, riceve **lo stesso token**.
- Questo evita di creare stanze extra solo perché il client ha avuto un timeout di rete.

---

## 4. Token di stanza

- Payload:
  ```json
  {
    "room_id": "...", //Id della stanza
    "lobby_id": "...", //Lobby che ha generato la stanza
    "issued_at": "...", //Data creazione
    "expires_at": "..." //Data di scadenza (segue l'avvio della partita, se arriva ci sono abbastanza giocatori)
  }

## 5. Realtime di gioco nella stanza (CP best effort)

### 5.1 Connessione
1. Il client apre un socket verso il room server e presenta il token.
2. Il room server valida il token e aggiunge il giocatore alla stanza.
3. Quando il numero minimo di player è raggiunto, la stanza passa a “in partita”.

### 5.2 Game loop a tick
- Il room server lavora a **tick fissi** (10 oppure 20 ogni secondo):
  1. raccoglie input ricevuti nel tick corrente;
  2. li ordina usando `seq_num` per client (o timestamp logico);
  3. aggiorna lo stato di gioco in modo deterministico;
  4. invia ai client delta/snapshot dello stato.
- Questo rende l’ordine degli eventi indipendente da dalla latenza della rete.

### 5.3 Gestione partizioni e disconnessioni
- La stanza resta **CP**: lo stato è unico e non viene mai “forkato” sui client.
- Se un client non comunica per `T_disconnect`:
  - viene marcato disconnesso e rimosso dal loop;
  - la partita continua per gli altri (**A best effort globale**).
- Rejoin (DA VALUTARE CON ENRICO):
  - opzionale ma chiarito nel progetto: rejoin possibile entro `T_rejoin` riusando il token o un nuovo token di rejoin; oltre la finestra, il giocatore è considerato fuori.

---

## 6. Sintesi CAP per il report

- **Lobby = CP**  
  Obiettivo: trovare rapidamente una stanza e far partire partite anche con peer parzialmente irraggiungibili.  
  Compromesso accettato: in casi rari si creano più stanze del necessario.

- **Room = CP (A best effort)**  
  Obiettivo: stato di gioco unico e consistente, fondamentale per bomb placement, esplosioni e collisioni.  
  Compromesso accettato: client instabili vengono disconnessi per non contaminare lo stato.

---
