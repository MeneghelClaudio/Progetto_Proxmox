# 🛠️ Proxmox Web Management Orchestrator (PWMO)

## 📌 Descrizione
PWMO è una **web application cloud-ready basata su architettura a microservizi**, progettata per semplificare la gestione di infrastrutture **Proxmox VE** per operatori MSP.

L’obiettivo è fornire una dashboard centralizzata per il monitoraggio e il controllo di VM e container (LXC), riducendo la complessità dell’interfaccia nativa di Proxmox. fileciteturn1file0

---

## 🎯 Obiettivi principali
- Accesso semplificato alle risorse Proxmox
- Dashboard unica per stato, risorse e backup
- Architettura scalabile e cloud-ready
- Gestione sicura delle credenziali

---

## 🏗️ Architettura

L’applicazione è completamente containerizzata tramite **Docker** e orchestrata con `docker-compose`.

### Componenti:
- **Backend**: API per comunicazione con Proxmox
- **Frontend**: Interfaccia utente web
- **Database (esterno)**: AWS RDS per persistenza
- **Security Layer**: AWS Secrets Manager
- **Container Registry**: AWS ECR

---

## ⚙️ Tecnologie

### Backend
- Python (es. FastAPI)

### Frontend
- HTML / CSS / JavaScript (o framework moderni)

### Database
- MariaDB (in produzione tramite AWS RDS)

### Cloud & DevOps
- Docker & Docker Compose
- AWS RDS
- AWS Secrets Manager
- AWS ECR

---

## 🔐 Sicurezza
- Utilizzo esclusivo di **API Token Proxmox**
- Nessuna credenziale hardcoded
- Recupero dinamico dei segreti tramite AWS Secrets Manager

---

## 🚀 Funzionalità Core (Livello 1)

### 📊 Dashboard
- Stato dei nodi (CPU, RAM, Storage)

### 🖥️ Inventory
- Lista completa di VM e container (ID, nome)

### ⚡ Power Management
- Start / Stop / Shutdown / Reboot

### 📈 Monitoring
- Utilizzo CPU e RAM (ultimi 30 minuti)

### 💾 Backup
- Avvio snapshot manuale
- Storico backup (PBS)

### ☁️ Cloud Integration
- Connessione a DB esterno (AWS RDS)
- Gestione segreti con AWS Secrets Manager
- Deploy immagini su AWS ECR fileciteturn1file0

---

## ⭐ Funzionalità Bonus (Livello 2)
- Cluster awareness (multi-nodo)
- Live migration delle VM

---

## ▶️ Avvio del progetto

### Requisiti
- Docker
- Docker Compose
- Accesso a servizi AWS (RDS, Secrets Manager, ECR)

### Avvio
```bash
# Clona il repository
git clone <repo-url>
cd pwmo

# Avvia lo stack
docker-compose up --build
```

---

## 📂 Struttura progetto

```
/backend
/frontend
/docker-compose.yml
/README.md
```

---

## 🔌 API Proxmox (Esempi)

```http
GET /api2/json/nodes
GET /api2/json/nodes/{node}/qemu
POST /api2/json/nodes/{node}/qemu/{vmid}/status/start
```

---

## ⚠️ Note tecniche
- I valori Proxmox devono essere normalizzati (CPU %, RAM in byte)
- Gestione errori obbligatoria (es. PBS non raggiungibile)
- L’applicazione non deve crashare in caso di errore fileciteturn1file0

---

## 🧪 Test
Il progetto include un **Test Plan** per verificare:
- correttezza delle API
- comunicazione con Proxmox
- gestione errori

---

## 📦 Deliverable
- Codice sorgente (Frontend + Backend)
- Dockerfile + docker-compose
- README.md
- Test Plan
- Presentazione progetto fileciteturn1file0

---

## 👨‍💻 Autore
Progetto sviluppato per INFORMIX Spa - Project Work PWMO.
