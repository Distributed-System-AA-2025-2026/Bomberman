# Room

## Roadmap
- fare gioco astratto
  - grid, player, bomb, wall
    - movimento player
    - posizionamento bomba
    - esplosione bomba
    - ecc...
  - interfaccia testuale per provare il gioco

- ogni azione che fa il player (client) è chiamata da una sua funzione

## Comportamento Client - Room
- La room è il gioco, dice se il client fa mosse corrette e aggiorna lo stato del gioco
- La room comunica con il client tramite TCP e un protocollo custom protobuf
- Client cerca  la partita -> Room mette in coda il client -> Client riceve che è in coda -> Room cerca di far partire la partita quando ci sono abbastanza giocatori (>1) -> Room invia a tutti i client la partita iniziata -> Client riceve lo stato iniziale del gioco -> Client invia azione all'istante x -> Room riceve x e azione e convalida -> Se valida aggiorna lo stato del gioco e invia a tutti i client (broadcast) lo stato aggiornato -> Client riceve stato aggiornato e aggiorna la UI (Consistency)
- Se un client si disconnette involontariamente (es. perdita connessione) il cliente si autoconvalida il gioco e poi appena si riconnette il server rimanda lo stato del gioco aggiornato (Partition Failure)
  - Se client si disconnette involontariemente
    - Il server aspetta un tot di tempo (es. 30 secondi) per la riconnessioneient si riconnette
      - Se si riconnette in tempo
        - Il server rimanda lo stato del gioco aggiornato
      - Se non si riconnette in tempo
        - Il server elimina il client dalla partita e aggiorna lo stato del gioco
- Se un client si disconnette volontariamente (es. esce dal gioco) il server elimina il client dalla partita e aggiorna lo stato del gioco