# Proxmox Manager

Web app per la gestione centralizzata di cluster Proxmox VE, stile VMware
Workstation: albero delle risorse, grafici real-time a 1 Hz su finestra di 30 min,
azioni VM/CT con doppia conferma, snapshot, backup, e migrazione drag & drop con
task bar di progresso.

**Stack**

- **Backend**: Python 3.12 + FastAPI + [proxmoxer](https://github.com/proxmoxer/proxmoxer)
- **Frontend**: HTML + Tailwind (CDN) + Chart.js + vanilla ES6 modules
- **DB**: MariaDB 11 (users, credenziali cifrate, task di migrazione)
- **Deployment**: Docker Compose, esposto su `:8027`

---

## Quick start

```bash
git clone <repo> proxmox-manager
cd proxmox-manager
cp .env.example .env
# modifica .env: password DB, JWT_SECRET, (opz.) FERNET_KEY
docker compose up -d --build
# apri http://localhost:8027
# login iniziale:  admin / admin   → cambiala subito
```

### Generare una chiave Fernet stabile (consigliato in produzione)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Mettila in `FERNET_KEY=` nel file `.env`. Se la lasci vuota, la chiave viene
generata al primo avvio e persiste nel volume `backend_data` (`/data/fernet.key`).
Se la chiave cambia, le credenziali Proxmox salvate **non saranno più
decifrabili** e dovrai inserirle di nuovo — quindi conservala.

---

## Cosa offre la UI

- **Sidebar ad albero** con Cluster 🧩, Nodi fisici 🖥️, VM 🧊, CT 📦, Storage
  💽, Backup storage 💾. Le VM/CT sono trascinabili su un altro nodo per
  avviare una migrazione.
- **Main view post-login** con tre tab: *Server fisici* (card con CPU/RAM),
  *Cluster* (stato, quorum, versione), *Backup* (storage con percentuali di
  occupazione).
- **Pannello destro** per la risorsa selezionata:
  - CPU e RAM live in tempo reale via **WebSocket a 1 Hz**, finestra di
    **30 minuti scorrevole**.
  - Azioni: **Start / Stop / Shutdown / Reboot / Clone / Delete**.
  - Clone e Delete mostrano un **modal di conferma con nome**: devi digitare
    il nome corrente della VM/CT, stile GitHub-delete-repo.
  - **History** con tutti gli snapshot (data, ora, descrizione) + pulsanti
    rollback ed eliminazione.
- **Task bar in fondo**: mostra le migrazioni in corso con percentuale di
  completamento (derivata parsando il log del task PVE).

---

## Sicurezza

- Le password di Proxmox **non sono mai salvate in chiaro**: vengono cifrate
  con **Fernet** (AES-128-CBC + HMAC-SHA256) al momento del `POST
  /api/credentials` e decifrate in RAM solo quando serve costruire il client
  `proxmoxer`.
- Le password utente del login locale sono **bcrypt-hashed** via `passlib`.
- L'autenticazione API è via **JWT** HS256, TTL 8 h (vedi `JWT_EXPIRE_MINUTES`).
- I certificati self-signed di Proxmox sono supportati (`verify_ssl=False`
  sulla credenziale); il warning InsecureRequest è silenziato lato backend.
- Il frontend e il backend condividono origine via nginx reverse-proxy
  (nessuna CORS permissiva in produzione; cambia `CORS_ORIGINS` se esponi il
  backend direttamente).

### Cambiare la password admin

Login con `admin/admin`, poi da un terminale Python o Swagger
(`http://localhost:8027/api/docs`):

```bash
TOKEN=$(curl -s -X POST http://localhost:8027/api/auth/login \
  -d 'username=admin&password=admin' | jq -r .access_token)

curl -X POST http://localhost:8027/api/auth/users \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"username":"mario","password":"nuovapass","is_admin":true}'
```

Poi elimina l'utente `admin` in MariaDB, o (meglio in un secondo momento) aggiungi
un endpoint di change-password.

---

## Endpoint principali

| Metodo | Path | Descrizione |
|---|---|---|
| `POST` | `/api/auth/login` | ottiene JWT |
| `GET`  | `/api/credentials` | elenca cluster configurati |
| `POST` | `/api/credentials` | aggiunge un cluster (password cifrata) |
| `GET`  | `/api/clusters/{cid}/tree` | payload completo dell'albero |
| `GET`  | `/api/clusters/{cid}/nodes/{node}/rrd` | storico RRD |
| `GET`  | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}` | stato + config |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/{start,stop,shutdown,reboot}` | azioni |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/clone` | clonazione |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/delete` | eliminazione (con `confirm_name`) |
| `POST` | `/api/clusters/{cid}/vms/{kind}/{node}/{vmid}/migrate` | migrazione in background |
| `GET`  | `/api/clusters/{cid}/snapshots/{kind}/{node}/{vmid}` | snapshot history |
| `POST` | `/api/clusters/{cid}/snapshots/...` | create / rollback / delete |
| `POST` | `/api/clusters/{cid}/backups/{node}/{vmid}` | vzdump on demand |
| `GET`  | `/api/tasks?active=true` | migrazioni in corso |
| `WS`   | `/api/ws/stats?token=...` | stream 1 Hz CPU/RAM |

Documentazione Swagger interattiva su `/api/docs`.

---

## Struttura del progetto

```
proxmox-manager/
├── docker-compose.yml         # 3 servizi: db, backend, frontend (porta 8027)
├── .env.example
├── db/init.sql                # schema + utente bootstrap admin/admin
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # FastAPI + WebSocket
│       ├── config.py          # settings + gestione chiave Fernet
│       ├── database.py, models.py, schemas.py
│       ├── crypto.py          # Fernet + bcrypt
│       ├── auth.py            # JWT
│       ├── proxmox_client.py  # wrapper proxmoxer
│       ├── websocket.py       # stream stats a 1 Hz
│       ├── tasks.py           # runner migrazione background
│       └── routers/
│           ├── auth_router.py, credentials.py, cluster.py,
│           ├── vms.py, snapbackup.py, tasks_router.py
└── frontend/
    ├── Dockerfile, nginx.conf  # reverse proxy /api + WS upgrade
    ├── index.html, login.html
    ├── css/app.css
    └── js/
        ├── api.js              # fetch + JWT
        ├── tree.js             # albero sidebar + drag source/target
        ├── charts.js           # Chart.js + WebSocket, 30 min
        ├── detail.js           # pannello VM/CT stile Workstation
        ├── overview.js         # main tabs
        ├── tasks.js            # task bar + migrazione
        ├── modal.js            # conferma-per-nome
        └── main.js             # glue + auth guard
```

---

## Sviluppo locale (senza Docker)

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DB_HOST=127.0.0.1 DB_USER=pmxuser DB_PASSWORD=pmxpass DB_NAME=proxmox_manager
export JWT_SECRET=dev
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
python -m http.server 8080     # o qualsiasi static server
# punta le chiamate /api/ a http://localhost:8000 via nginx / proxy del tuo editor
```

---

## Note operative

- **Scaling dei grafici**: Chart.js gestisce bene 1800 punti (30 min × 60 s).
  Se vuoi scendere a 500 ms o allargare la finestra, modifica `POLL_INTERVAL`
  (env del backend) e `WINDOW_SECONDS` in `frontend/js/charts.js`.
- **Progresso migrazione**: estratto parsando righe `progress NN%` dal log
  del task PVE (`/nodes/{n}/tasks/{upid}/log`). È un'euristica — migrazioni
  su storage condiviso completano quasi istantaneamente e mostrano 99→100 %.
- **Deploy in produzione**: metti il frontend dietro un reverse-proxy HTTPS
  (Caddy/Traefik) e cambia `CORS_ORIGINS` + `JWT_SECRET`. Considera
  l'uso di un API-token Proxmox invece di user/password (TODO — richiede
  un piccolo cambio in `proxmox_client.build_client`).

---

## Licenza

MIT (o quello che preferisci — scheletro pronto all'uso).
