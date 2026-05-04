# AWS Secrets Manager — Proxmox Manager

## Secret name

```
proxmox-manager/config
```

Crea il secret con la AWS CLI:

```bash
aws secretsmanager create-secret \
  --name "proxmox-manager/config" \
  --region eu-west-1 \
  --secret-string '{
    "DB_HOST":     "your-rds-endpoint.rds.amazonaws.com",
    "DB_PORT":     "3306",
    "DB_NAME":     "proxmox_manager",
    "DB_USER":     "pmxuser",
    "DB_PASSWORD": "CHANGE_ME_strong_password",
    "JWT_SECRET":  "CHANGE_ME_long_random_string_min_32_chars",
    "FERNET_KEY":  "CHANGE_ME_run_command_below"
  }'
```

Per generare `FERNET_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Chiavi del secret (tutte)

| Chiave | Tipo | Descrizione | Valore di esempio |
|--------|------|-------------|-------------------|
| `DB_HOST` | string | Endpoint RDS (senza porta) | `pmx.xxxxxxxxxxxx.eu-west-1.rds.amazonaws.com` |
| `DB_PORT` | string | Porta MySQL/MariaDB su RDS | `3306` |
| `DB_NAME` | string | Nome del database | `proxmox_manager` |
| `DB_USER` | string | Utente del database | `pmxuser` |
| `DB_PASSWORD` | string | Password del database — scegliere una stringa forte | `S3cur3P@ssw0rd!` |
| `JWT_SECRET` | string | Chiave segreta per firmare i token JWT (≥ 32 caratteri random) | `a9f3k2...` (64 hex chars) |
| `FERNET_KEY` | string | Chiave Fernet (AES-128-CBC) per cifrare le password Proxmox salvate nel DB. Base64 url-safe, 44 caratteri. | `T3BlbnNzaC1rZXktdjE...` |

> **Nota:** `DB_PORT` viene salvato come stringa nel JSON ma il backend lo converte automaticamente a intero.

---

## Variabili NON nel secret (rimangono in env / docker-compose)

Queste non sono sensibili e non hanno bisogno di Secrets Manager.

| Variabile | Dove si imposta | Descrizione | Valore tipico |
|-----------|----------------|-------------|---------------|
| `AWS_REGION` | `.env` / docker-compose | Region AWS dove si trova il secret | `eu-west-1` |
| `AWS_SECRET_NAME` | `.env` / docker-compose | Nome del secret da recuperare | `proxmox-manager/config` |
| `AWS_ACCESS_KEY_ID` | `.env` / docker-compose | IAM access key (solo per Docker locale — su ECS/EC2 usare il task/instance role) | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | `.env` / docker-compose | IAM secret key (solo per Docker locale) | `wJalrXUtnFEMI/K7MDENG/...` |
| `CORS_ORIGINS` | docker-compose | Origini CORS permesse | `*` |

---

## IAM Policy minima

Il principal (IAM user o task role) deve avere almeno:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:eu-west-1:ACCOUNT_ID:secret:proxmox-manager/config-*"
    }
  ]
}
```

---

## Rotazione delle chiavi

| Chiave | Come ruotare |
|--------|-------------|
| `DB_PASSWORD` | Aggiorna su RDS → aggiorna il secret → riavvia il container backend |
| `JWT_SECRET` | Aggiorna il secret → riavvia il backend (tutti i token esistenti vengono invalidati) |
| `FERNET_KEY` | ⚠️ Non ruotare senza prima re-cifrare tutte le `encrypted_password` nel DB — le password Proxmox salvate diventerebbero illeggibili |

---

## ECR — push dell'immagine backend

```bash
# Autenticazione
aws ecr get-login-password --region eu-west-1 | \
  docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.eu-west-1.amazonaws.com

# Build & push
docker build -t proxmox-manager-backend ./backend
docker tag  proxmox-manager-backend:latest \
            ACCOUNT_ID.dkr.ecr.eu-west-1.amazonaws.com/proxmox-manager-backend:latest
docker push ACCOUNT_ID.dkr.ecr.eu-west-1.amazonaws.com/proxmox-manager-backend:latest
```

Stessa procedura per il frontend (`./frontend`), usando un repository ECR separato.
