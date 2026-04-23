# ProxMox Manager

Control panel per Proxmox VE con backend FastAPI + MariaDB e frontend vanilla JS/CSS ispirato a Proxmox (tema dark, accent arancione, sidebar con albero cluster).

## Architettura

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│   Browser   │───▶│  nginx :8027 │───▶│ FastAPI :8000│
└─────────────┘    │   (frontend) │    │  (backend)   │
                   └──────────────┘    └──────┬───────┘
                                              │
                                    ┌─────────┼──────────┐
                                    │                    │
                                    ▼                    ▼
                              ┌──────────┐       ┌────────────┐
                              │ MariaDB  │       │  Proxmox   │
                              │  :3306   │       │  API :8006 │
                              └──────────┘       └────────────┘
```

- **backend** — FastAPI con JWT auth, SQLAlchemy/MariaDB, Fernet encryption per le credenziali Proxmox, WebSocket per le live stats
- **frontend** — HTML/CSS/JS vanilla (nessun framework), identico nello stile al mockup `prostatamox` ma alimentato da dati reali del backend
- **db** — MariaDB 11, schema inizializzato da `db/init.sql` al primo avvio

## Ruoli

Tre livelli gerarchici, gestibili dalla pagina **Utenti &amp; Permessi** (solo admin):

| Ruolo  | Dashboard / visualizza | Start/Stop/Reboot | Clone / Migrate / Snapshot / Backup | Delete VM / snapshot / user mgmt | Aggiungi/Rimuovi server |
|--------|:-:|:-:|:-:|:-:|:-:|
| **admin**  | ✔ | ✔ | ✔ | ✔ | ✔ / ✔ |
| **senior** | ✔ | ✔ | ✔ | ✘ | ✔ / ✘ |
| **junior** | ✔ | ✘ | ✘ | ✘ | ✘ / ✘ |

I controlli sono applicati **sia** in frontend (pulsanti nascosti) **sia** nel backend (dipendenze `require_senior` / `require_admin`). Il frontend è solo UX: il backend è la fonte di verità.

## Avvio rapido

```bash
# 1. Clona e configura
cp .env.example .env
# (opzionale) modifica JWT_SECRET e le password DB in .env

# 2. Avvia
docker compose up -d --build

# 3. Apri il browser
open http://localhost:8027
```

**Credenziali iniziali**: `admin` / `admin` → **cambia la password al primo login** dalla pagina Utenti.

## Primo utilizzo

1. Login come `admin`
2. Vai su **Server Proxmox** → **Aggiungi server**: inserisci host, porta (8006), utente PVE (es. `root@pam`), password del cluster
3. Ritorna alla **Dashboard**: vedrai nodi, VM, container e storage del cluster reale
4. Crea gli utenti `senior` / `junior` dalla pagina **Utenti &amp; Permessi**

## Struttura del progetto

```
proxmox-manager/
├── docker-compose.yml
├── .env.example
├── README.md
├── db/
│   └── init.sql             # schema + utente admin iniziale
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py          # FastAPI entrypoint
│       ├── config.py        # settings (env) + Fernet bootstrap
│       ├── database.py      # SQLAlchemy engine/session
│       ├── models.py        # User / ProxmoxCredential / MigrationTask
│       ├── schemas.py       # Pydantic request/response
│       ├── auth.py          # JWT + require_admin / require_senior
│       ├── crypto.py        # Fernet + bcrypt helpers
│       ├── proxmox_client.py# proxmoxer wrapper
│       ├── tasks.py         # background migration poller
│       ├── websocket.py     # live stats WS
│       └── routers/
│           ├── auth_router.py
│           ├── users_router.py  # CRUD utenti (admin only)
│           ├── credentials.py
│           ├── cluster.py
│           ├── vms.py
│           ├── snapbackup.py
│           ├── tasks_router.py
│           └── create.py
└── frontend/
    ├── Dockerfile
    ├── nginx.conf           # reverse-proxy verso backend + WS upgrade
    ├── index.html           # redirect login/dashboard
    ├── login.html           # senza demo accounts
    ├── dashboard.html
    ├── node-detail.html
    ├── vm-detail.html       # live stats via WebSocket
    ├── migration.html       # drag&drop → /vms/.../migrate
    ├── backup.html
    ├── servers.html         # gestione credenziali Proxmox
    ├── users.html           # CRUD utenti + matrice permessi
    ├── shared.css
    ├── api.js               # fetch wrapper + endpoint bindings
    ├── shared.js            # UI helpers (toast, tema, topbar)
    └── sidebar.js           # sidebar con albero cluster live
```

## Sicurezza

- Password utenti **bcrypt** (cost 12) — mai in chiaro
- Password Proxmox criptate con **Fernet** (AES-128-CBC + HMAC-SHA256). La chiave è in `/data/fernet.key` nel volume `backend_data` — **fai il backup** di quel volume, senza la chiave i credenziali Proxmox non sono recuperabili
- JWT firmati HS256, scadenza 8h (configurabile via `JWT_EXPIRE_MINUTES`)
- CORS `*` di default: metti il dominio esatto in produzione via `CORS_ORIGINS`
- `verify_ssl=false` è pensato per homelab con certificati self-signed; **abilitalo in produzione**

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `proxmox_manager` / `pmxuser` / `pmxpass` | Database |
| `DB_ROOT_PASSWORD` | `rootpass` | Password root MariaDB |
| `JWT_SECRET` | `change-me-in-production-please` | **CAMBIALA** |
| `FERNET_KEY` | vuoto (generata al primo avvio) | 32 byte base64. Per generarne una: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `CORS_ORIGINS` | `*` | Virgola per più origini |

## API

Documentazione interattiva: **http://localhost:8027/api/docs**

Endpoint principali:

- `POST /api/auth/login` — login, ritorna JWT
- `GET  /api/auth/me`
- `GET/POST/PATCH/DELETE /api/users` — gestione utenti (admin)
- `GET/POST/DELETE /api/credentials` — server Proxmox
- `GET /api/clusters/{cred_id}/tree` — albero cluster completo per la sidebar
- `POST /api/clusters/{cred_id}/vms/{kind}/{node}/{vmid}/{action}` — start/stop/shutdown/reboot/clone/migrate/delete
- `GET/POST/DELETE /api/clusters/{cred_id}/snapshots/...` — snapshot
- `POST /api/clusters/{cred_id}/backups/{node}/{vmid}` — backup
- `GET /api/tasks?active=true` — task di migrazione in corso
- `WS /api/ws/stats?token=...` — live metrics via subscribe

## Sviluppo locale (senza Docker)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DB_HOST=localhost DB_USER=... uvicorn app.main:app --reload --port 8000

# Frontend — basta servire la cartella statica e proxare /api/ al backend
cd frontend
python -m http.server 8080
# (per lo sviluppo, imposta API_BASE='http://localhost:8000' in api.js)
```

## Cambio password admin

Dal browser: login → **Utenti &amp; Permessi** → matita sull'utente `admin` → nuova password.
