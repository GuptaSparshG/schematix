# Schematix · Deployment Guide

Two deploy paths — pick one.

| Path | When to use | Time |
|---|---|---|
| **A · Docker Compose** | Any cloud VM with Docker (EC2, DigitalOcean, GCE, …) | ~10 min |
| **B · systemd + nginx** | Bare VM where you control Python/nginx directly | ~20 min |

Either way you'll need:
- A VM (2 vCPU, 2 GB RAM is plenty)
- Outbound HTTPS to `generativelanguage.googleapis.com`
- A Gemini API key from <https://aistudio.google.com/apikey> (free tier OK)

---

## Path A — Docker Compose (recommended)

```bash
# On the VM:
git clone <your-repo> /opt/schematix
cd /opt/schematix

# Configure
cp .env.example .env
nano .env            # paste GEMINI_API_KEY, set ALLOWED_ORIGINS=https://yourdomain.com

# Build & run
docker compose up -d --build

# Confirm
docker compose ps
curl http://localhost:8000/api/health     # {"status":"ok"}
```

**Open ports** in your cloud security group:
- `22` (SSH, your IP only)
- `8000` if testing without nginx → `http://<vm-ip>:8000`
- `80` + `443` once you put nginx in front

**Add HTTPS (nginx + Let's Encrypt):**

1. Point a DNS A-record at the VM (e.g. `schematix.example.com`).
2. Edit `deploy/nginx.conf` — replace `schematix.example.com` with your real domain.
3. Uncomment the `nginx` service in `docker-compose.yml`, or install nginx on the host.
4. Run certbot to fetch a cert: `sudo certbot --nginx -d schematix.example.com`
5. `docker compose restart` (or `systemctl reload nginx` if on host).

Users hit `https://schematix.example.com`. Schematix itself only listens on `127.0.0.1:8000`.

---

## Path B — systemd + nginx (no Docker)

```bash
# On the VM:
sudo useradd -r -m -d /opt/schematix schematix
sudo -u schematix bash << 'EOF'
cd /opt/schematix
git clone <your-repo> .
python3 -m venv circuit-venv
./circuit-venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env       # set GEMINI_API_KEY and ALLOWED_ORIGINS
EOF

# Install the service
sudo cp deploy/schematix.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now schematix

# Confirm
systemctl status schematix
curl http://localhost:8000/api/health

# nginx
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/schematix
sudo ln -s /etc/nginx/sites-available/schematix /etc/nginx/sites-enabled/
# Edit the file → replace schematix.example.com with your domain
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d schematix.example.com
```

---

## Production checklist

- [ ] `.env` filled in (`GEMINI_API_KEY`, `ALLOWED_ORIGINS` locked to your domain)
- [ ] `ALLOWED_ORIGINS` is NOT `*` — set it to `https://yourdomain.com`
- [ ] Only ports 80 + 443 (and SSH) open in the security group
- [ ] Schematix bound to `127.0.0.1`, not `0.0.0.0` (when behind nginx)
- [ ] TLS cert from Let's Encrypt (auto-renews via certbot timer)
- [ ] `output/` is mounted as a volume so history survives restarts
- [ ] systemd `Restart=on-failure` (already set) — service auto-recovers
- [ ] Cloud snapshots / VM-level backups of the `output/` directory

---

## Operations cheatsheet

```bash
# Logs
docker compose logs -f schematix
journalctl -u schematix -f

# Restart
docker compose restart schematix
sudo systemctl restart schematix

# Update code
git pull
docker compose up -d --build              # Docker path
sudo systemctl restart schematix          # systemd path

# Tail just errors
journalctl -u schematix -p err -f
```

---

## Endpoints (for monitoring / load balancers)

- `GET /api/health` → `{"status":"ok"}` · use as health-check target
- `GET /docs` → Swagger UI (you may want to lock this behind basic-auth in nginx)

## Resource expectations

- **Idle:** ~250 MB RAM, <1% CPU
- **During analysis (per request):** spike to ~400 MB RAM for ~5–8s
- **STL render (per request):** ~600 MB RAM for ~2–5s (matplotlib)
- **Concurrent users:** 1 vCPU comfortably handles 5–10 simultaneous analyses
