# Proxmox Manager

Web app per la gestione centralizzata di cluster Proxmox VE, stile VMware Workstation: albero delle risorse, grafici real-time a 1 Hz su finestra di 30 min, azioni VM/CT con doppia conferma, snapshot, backup, e migrazione drag & drop con task bar di progresso.

---

## Stack Tecnologico

| Layer | Tecnologia | Motivazione |
|---|---|---|
| **Backend** | Python 3.12 + FastAPI | Framework async ad alte prestazioni, generazione automatica OpenAPI/Swagger, validazione via Pydantic |
| **Frontend** | HTML + Tailwind CSS (CDN) + Chart.js + Vanilla ES6 | Nessun bundler necessario, deploy immediato via nginx statico |
| **Database** | MariaDB 11 | Gestione utenti, credenziali cifrate e task di migrazione persistenti |
| **Proxy Proxmox** | proxmoxer 2.x | Wrapper ufficiale per le API REST di Proxmox VE |
| **Autenticazione** | JWT HS256 (TTL 8 h) + bcrypt | Standard industriale, stateless, nessun session store |
| **Cifratura** | Fernet (AES-128-CBC + HMAC-SHA256) | Le password Proxmox non vengono mai salvate in chiaro |
| **Real-time** | WebSocket a 1 Hz | Aggiornamento grafici CPU/RAM senza polling HTTP ripetuto |
| **Deployment** | Docker Compose (3 servizi) | Isolamento, riproducibilità, zero dipendenze sull'host |
| **Segreti (prod)** | AWS Secrets Manager via boto3 | Credenziali sensibili fuori dal filesystem del container |

---

## Quick Start (Docker)

```bash
git clone <repo> proxmox-manager
cd proxmox-manager
cp .env.example .env
# Modifica .env: AWS_REGION, AWS_SECRET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
docker compose up -d
# Apri http://localhost:8027
# Login iniziale:  admin / admin  → cambiala subito!
```

### Generare una chiave Fernet stabile (produzione)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Aggiungi il risultato come `FERNET_KEY=` nel file `.env`.  
Se la chiave cambia, le credenziali Proxmox salvate non saranno più decifrabili.

---

## Scelte Tecniche

### Backend — FastAPI
FastAPI è stato scelto per:
- **Velocità di sviluppo**: decoratori intuitivi e validazione automatica via Pydantic.
- **Documentazione automatica**: Swagger UI disponibile su `/api/docs` senza configurazione aggiuntiva.
- **Async nativo**: gestione WebSocket e background task senza thread pool dedicati.
- **Tipizzazione forte**: riduce bug a runtime grazie ai type hint Python.

### Database — MariaDB + SQLAlchemy
- MariaDB garantisce compatibilità con l'ecosistema MySQL ed è ottimale per dataset relazionali di piccole-medie dimensioni.
- SQLAlchemy ORM consente migrazioni semplici e query sicure (no SQL injection).
- Lo schema viene inizializzato da `db/init.sql` e l'utente bootstrap `admin/admin` viene creato al primo avvio.

### Sicurezza
- **Credenziali Proxmox** cifrate con Fernet prima della persistenza su DB; decifrate in RAM solo al momento della connessione.
- **Password utenti** hashate con bcrypt (work factor adeguato).
- **JWT** con scadenza configurabile (`JWT_EXPIRE_MINUTES`); il token viene trasmesso solo via header `Authorization: Bearer`.
- **Nessuna CORS permissiva in produzione**: la variabile `CORS_ORIGINS` va impostata all'host reale.
- **Certificati self-signed Proxmox** supportati tramite `verify_ssl=False` per ambiente di lab.

### Frontend — Vanilla ES6 + Tailwind CDN
La scelta di non usare un framework SPA (React/Vue) è motivata da:
- **Semplicità di deploy**: file statici serviti da nginx, nessun build step.
- **Leggerezza**: Tailwind via CDN e Chart.js coprono il 100% dei requisiti UI.
- **Manutenibilità**: moduli ES6 nativi (`api.js`, `tree.js`, `charts.js`, ecc.) facilmente comprensibili senza toolchain.

### Real-time — WebSocket
Il feed statistiche (CPU/RAM) viaggia su WebSocket a 1 Hz verso ogni client connesso.  
La finestra scorrevole di 30 minuti (1800 punti) è gestita interamente da Chart.js lato frontend, senza persistenza sul backend.

### Docker Compose
Il progetto è composto da 2 servizi in produzione (immagini pre-buildate su ECR) e 3 in sviluppo locale (aggiungendo il container MariaDB):

| Servizio | Porta esposta | Descrizione |
|---|---|---|
| `pmx_backend` | 8000 (interno) | FastAPI + Uvicorn |
| `pmx_frontend` | 8027 | nginx (statico + reverse proxy `/api`) |
| `db` | 3306 (interno) | MariaDB 11 (solo sviluppo locale) |

---

## Struttura del Progetto

```
proxmox-manager/
├── docker-compose.yml          # Deployment produzione (immagini ECR)
├── docker-compose.dev.yml      # Sviluppo locale con MariaDB
├── .env                        # Variabili d'ambiente (non committare in produzione)
├── .env.example
├── db/
│   └── init.sql                # Schema DB + utente bootstrap admin/admin
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI entrypoint + WebSocket stats
│       ├── config.py           # Settings Pydantic + gestione chiave Fernet
│       ├── database.py         # Engine SQLAlchemy + session factory
│       ├── models.py           # ORM: User, ProxmoxCredential, MigrationTask
│       ├── schemas.py          # Pydantic I/O schemas
│       ├── crypto.py           # Fernet encrypt/decrypt + bcrypt
│       ├── auth.py             # JWT create/verify + dependency guards
│       ├── proxmox_client.py   # Wrapper proxmoxer (build_client, vm_*, node_*)
│       ├── websocket.py        # Stream stats CPU/RAM a 1 Hz
│       ├── tasks.py            # Background runner migrazione
│       ├── state.py            # Cache albero + revision counter
│       └── routers/
│           ├── auth_router.py  # POST /api/auth/login, GET /api/auth/me
│           ├── users_router.py # CRUD utenti (admin only)
│           ├── credentials.py  # CRUD cluster/credenziali
│           ├── cluster.py      # Albero risorse, nodi, RRD
│           ├── vms.py          # Start/stop/clone/migrate/delete VM e CT
│           ├── snapbackup.py   # Snapshot e backup
│           ├── tasks_router.py # Stato migrazioni in corso
│           └── create.py       # Creazione VM e CT
└── frontend/
    ├── Dockerfile
    ├── nginx.conf              # Reverse proxy /api + WS upgrade
    ├── index.html              # Shell SPA post-login
    ├── login.html
    ├── dashboard.html
    ├── vm-detail.html
    ├── node-detail.html
    ├── cluster.html
    ├── servers.html
    ├── backup.html
    ├── migration.html
    ├── iso-upload.html
    ├── users.html
    ├── shared.css
    ├── shared.js               # Utility condivise
    ├── api.js                  # fetch wrapper + JWT injection
    └── sidebar.js              # Albero sidebar + drag & drop migrazione
```

---

## Endpoint Principali

| Metodo | Path | Ruolo minimo | Descrizione |
|---|---|---|---|
| `POST` | `/api/auth/login` | — | Ottiene JWT |
| `GET` | `/api/auth/me` | user | Profilo utente corrente |
| `GET` | `/api/credentials` | user | Elenca cluster configurati |
| `POST` | `/api/credentials` | user | Aggiunge cluster (password cifrata) |
| `GET` | `/api/clusters/{cid}/tree` | user | Albero completo risorse |
| `GET` | `/api/clusters/all` | user | Tutti i cluster (stale-while-revalidate) |
| `GET` | `/api/clusters/{cid}/nodes/{node}/rrd` | user | Storico RRD nodo |
| `GET` | `/api/clusters/{cid}/nodes/{node}/resources` | user | Risorse nodo per form creazione |
| `POST` | `/api/clusters/{cid}/nodes/{node}/qemu` | senior | Crea VM |
| `POST` | `/api/clusters/{cid}/nodes/{node}/lxc` | senior | Crea Container |
| `GET` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}` | user | Stato + config VM/CT |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/start` | senior | Avvia VM/CT |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/stop` | senior | Stop forzato |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/shutdown` | senior | Shutdown graceful |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/reboot` | senior | Riavvio |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/clone` | senior | Clonazione |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/migrate` | senior | Migrazione live |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/delete` | admin | Eliminazione (con `confirm_name`) |
| `GET` | `/api/clusters/{cid}/snapshots/{kind}/{node}/{vmid}` | user | Lista snapshot |
| `POST` | `/api/clusters/{cid}/snapshots/{kind}/{node}/{vmid}` | senior | Crea snapshot |
| `POST` | `/api/clusters/{cid}/snapshots/.../rollback` | senior | Rollback snapshot |
| `DELETE` | `/api/clusters/{cid}/snapshots/...` | admin | Elimina snapshot |
| `POST` | `/api/clusters/{cid}/backups/{node}/{vmid}` | senior | Backup on-demand (vzdump) |
| `GET` | `/api/tasks` | user | Migrazioni in corso |
| `WS` | `/api/ws/stats?token=...` | user | Stream 1 Hz CPU/RAM |
| `GET` | `/api/health` | — | Healthcheck |

Documentazione Swagger interattiva disponibile su **`/api/docs`**.

---

## Sviluppo Locale (senza Docker)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DB_HOST=127.0.0.1 DB_USER=pmxuser DB_PASSWORD=pmxpass DB_NAME=proxmox_manager
export JWT_SECRET=dev-secret-change-in-prod
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
python -m http.server 8080
# Assicurati che /api/* punti a http://localhost:8000 via proxy del tuo editor o nginx locale
```

---

## Gestione Utenti e Ruoli

Il sistema prevede tre livelli di accesso:

| Ruolo | Permessi |
|---|---|
| `user` | Lettura cluster, VM, nodi, snapshot |
| `senior` | + Azioni power, clone, migrazione, creazione, snapshot, backup |
| `admin` | + Eliminazione VM/CT, eliminazione snapshot, gestione utenti |

### Cambiare la password admin (primo avvio)

```bash
TOKEN=$(curl -s -X POST http://localhost:8027/api/auth/login \
  -d 'username=admin&password=admin' | jq -r .access_token)

# Crea nuovo utente admin
curl -X POST http://localhost:8027/api/auth/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"mario","password":"nuovapass","is_admin":true}'
```

---

## Note Operative

- **Scaling grafici**: Chart.js gestisce 1800 punti (30 min × 60 s). Per modificare la frequenza, aggiorna `POLL_INTERVAL` nel backend e `WINDOW_SECONDS` in `frontend/shared.js`.
- **Progresso migrazione**: estratto parsando righe `progress NN%` dal log del task PVE. Le migrazioni su storage condiviso completano quasi istantaneamente.
- **Deploy produzione**: esponi il frontend via HTTPS (Caddy/Traefik), imposta `CORS_ORIGINS` all'host reale e sostituisci `JWT_SECRET` con un valore sicuro.
- **API Token Proxmox**: è possibile usare un API token invece di user/password modificando `proxmox_client.build_client` (TODO nella roadmap).

---

## Licenza

MIT
