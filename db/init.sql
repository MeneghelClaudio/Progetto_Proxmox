-- Proxmox Manager initial schema
-- Loaded automatically by the mariadb container on first start

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,               -- bcrypt hash (never stored in clear)
    is_admin      TINYINT(1)   NOT NULL DEFAULT 0,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS proxmox_credentials (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    user_id            INT           NOT NULL,
    name               VARCHAR(128)  NOT NULL,          -- friendly label shown in the UI
    host               VARCHAR(255)  NOT NULL,
    port               INT           NOT NULL DEFAULT 8006,
    pve_username       VARCHAR(128)  NOT NULL,          -- e.g. root
    pve_realm          VARCHAR(32)   NOT NULL DEFAULT 'pam',
    encrypted_password BLOB          NOT NULL,          -- Fernet ciphertext
    verify_ssl         TINYINT(1)    NOT NULL DEFAULT 0,
    created_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uniq_user_name (user_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS migration_tasks (
    id          VARCHAR(64)   PRIMARY KEY,              -- uuid
    user_id     INT           NOT NULL,
    cred_id     INT           NOT NULL,
    vmid        INT           NOT NULL,
    kind        VARCHAR(16)   NOT NULL,                 -- 'qemu' | 'lxc'
    source_node VARCHAR(128)  NOT NULL,
    target_node VARCHAR(128)  NOT NULL,
    status      VARCHAR(32)   NOT NULL DEFAULT 'pending',
    progress    INT           NOT NULL DEFAULT 0,
    upid        VARCHAR(255),                           -- Proxmox Unique Process ID
    message     TEXT,
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (cred_id) REFERENCES proxmox_credentials(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Bootstrap admin user (username: admin / password: admin) - CHANGE ON FIRST LOGIN
-- Hash below is bcrypt for "admin"
INSERT INTO users (username, password_hash, is_admin)
VALUES ('admin', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 1)
ON DUPLICATE KEY UPDATE username=username;
