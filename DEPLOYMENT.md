# Production Deployment Guide: MS Project Centralized Resource & Template Hub

This portal can run **100% on local infrastructure (On-Premises)** or in the **Azure Cloud**.

Because the portal is fully containerized with Docker, you can deploy it on:
1. **Local Infrastructure (Recommended if keeping servers on-premise):**
   - Any local Linux VM (Ubuntu, Debian, RHEL, Rocky Linux) or Windows Server running Docker.
   - Behind your internal corporate network / reverse proxy (NGINX, IIS, Traefik).
2. **Azure Cloud:**
   - Azure Container Apps / Azure App Service (Linux) + Azure Database for PostgreSQL Flexible Server.

---

## 1. Network & Firewall Requirements (On-Premises)

When running on local infrastructure, the server needs:

| Direction | Port / Protocol | Destination | Purpose |
|---|---|---|---|
| **Outbound** | `443` (HTTPS) | `login.microsoftonline.com`<br>`graph.microsoft.com` | Authenticating and querying Microsoft Entra ID (Graph API) for selective user & group sync. |
| **Inbound** | `80` / `443` (HTTP/HTTPS) or `8000` | Local Network / Intranet | Allowing PMs and Admins within your company LAN or VPN to access the portal. |

> [!NOTE]
> **No public inbound internet access is required.** The portal can remain strictly internal on your corporate LAN/VPN. The only external connection is outbound HTTPS to Microsoft's APIs.

---

## 2. Option A: Local On-Premises Deployment (Docker Compose)

### Architecture
```mermaid
flowchart TD
    subgraph Local Server ["On-Premises Server / VM (Linux or Windows Server)"]
        subgraph Docker ["Docker Environment"]
            Portal["MPP Web Portal (FastAPI + React/HTML + OpenJDK/MPXJ)"]
            DB[("PostgreSQL 16 (or SQLite volume)")]
        end
        ReverseProxy["Internal Reverse Proxy (NGINX / IIS / Traefik)"]
        ReverseProxy -->|http://localhost:8000| Portal
        Portal --> DB
    end

    Users["Company Users / PMs (LAN or VPN)"] --> ReverseProxy
    Portal -->|Outbound HTTPS (Port 443)| Entra["Microsoft Entra ID (Graph API)"]
```

### Setup Steps

1. **Clone or Copy Repository:**
   Copy the application directory to your server (e.g. `/opt/mpp-portal` or `C:\Services\mpp-portal`).

2. **Configure Environment (`.env`):**
   Create or update your `.env` file with your Azure App Registration credentials:
   ```env
   # Microsoft Entra ID
   AZURE_AD_CLIENT_ID=your-client-id
   AZURE_AD_TENANT_ID=your-tenant-id
   AZURE_AD_CLIENT_SECRET=your-client-secret

   # Security & Session
   SECRET_KEY=generate-a-strong-random-key-here
   ENVIRONMENT=production
   ```

3. **Start the Service:**
   
   * **With PostgreSQL (Recommended for multi-user production):**
     ```bash
     docker compose up -d --build
     ```
     This starts both PostgreSQL and the portal container with health checks and persistent volume storage (`postgres_data`).

   * **With SQLite (Lightweight single-container setup):**
     ```bash
     docker compose -f docker-compose.sqlite.yml up -d --build
     ```
     Database file is persisted in `./data/mpp_hub.db`.

4. **Verify Deployment:**
   Check container logs and health:
   ```bash
   docker compose ps
   docker compose logs -f backend
   curl http://localhost:8000/health
   ```
   Open `http://<your-server-ip>:8000` in your browser.

---

## 3. Reverse Proxy Configuration (HTTPS on Local Intranet)

To serve the portal securely under your internal domain (e.g., `https://mpp.garantgroup.eu`):

### NGINX Example (`/etc/nginx/sites-available/mpp.conf`):
```nginx
server {
    listen 80;
    server_name mpp.garantgroup.eu;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mpp.garantgroup.eu;

    ssl_certificate     /etc/ssl/certs/garantgroup.crt;
    ssl_certificate_key /etc/ssl/private/garantgroup.key;

    # Allow larger file uploads for MS Project .mpp files
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Windows Server IIS Example:
- Install **URL Rewrite** and **Application Request Routing (ARR)** modules.
- Set up a Reverse Proxy rule forwarding incoming traffic to `http://127.0.0.1:8000`.

---

## 4. Option B: Azure Cloud Deployment

If you choose to run in Azure in the future:

1. **Container Image:**
   Build and push the Docker image to **Azure Container Registry (ACR)**:
   ```bash
   az acr build --registry <your-acr-name> --image mpp-portal:latest .
   ```

2. **Azure Container Apps:**
   - Deploy as a Container App linked to ACR.
   - Resource allocation: **0.5 vCPU, 1.0 GiB RAM** (sufficient for 10 PMs / 30 projects).
   - Ingress: Enabled (Internal or External depending on your network setup).

3. **Database:**
   - Provision **Azure Database for PostgreSQL Flexible Server** (Burstable tier `B1ms`).
   - Set environment variable:
     ```env
     DATABASE_URL=postgresql://<admin>:<password>@<server>.postgres.database.azure.com:5432/mpp_hub?sslmode=require
     ```

4. **Secrets:**
   - Store `AZURE_AD_CLIENT_SECRET` in Azure Container Apps Secret Store or Azure Key Vault.

---

## 5. Maintenance & Backup Strategy

### Database Backup (Local On-Premises)

* **PostgreSQL Backup (Daily Cron Job):**
  ```bash
  docker compose exec -t db pg_dump -U postgres mpp_hub > /backups/mpp_hub_$(date +%Y%m%d).sql
  ```

* **SQLite Backup:**
  Simply back up the `./data/mpp_hub.db` file (e.g., via standard backup agent or scheduled copy).

### Updating the Portal
When new versions or features are pulled from Git:
```bash
git pull origin main
docker compose up -d --build
```
Database tables and seeds are migrated automatically on startup.
