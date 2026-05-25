# DigitalOcean Infrastructure for Vela

## Overview

The Vela service desk voice intake stack requires four tiers of DigitalOcean resources:

```
┌─────────────────────────────────────────────────────────────┐
│                    DigitalOcean Account                     │
│                                                             │
│  ┌──────────────────┐     ┌──────────────────────────────┐ │
│  │   Droplet (AVR)  │     │   App Platform               │ │
│  │                  │────▶│   vela-adapter               │ │
│  │  avr-asterisk    │     │   (auto-scaled container)    │ │
│  │  avr-core        │     └──────────┬───────────────────┘ │
│  │  avr-asr-*       │               │                      │
│  │  avr-tts-*       │               ▼                      │
│  │  n8n             │     ┌──────────────────────────────┐ │
│  └──────────────────┘     │  DO Serverless Inference     │ │
│                           │  router:gmi-service-desk     │ │
│                           │  (no infrastructure needed)  │ │
│                           └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Resource 1: DO Serverless Inference

**Product:** DigitalOcean Inference (GenAI Platform)  
**Cost:** Pay-per-token (no infrastructure to provision)  
**Action required:** Generate an API key

### Setup
1. Go to **DO Dashboard → AI & ML → Inference**
2. Create an **API Key** and copy it
3. Set `MODEL_ACCESS_KEY=<your-key>` in your environment

The model `router:gmi-service-desk` is a hosted endpoint — no cluster or server needed.

---

## Resource 2: vela-adapter (App Platform)

**Product:** DO App Platform  
**Recommended size:** `apps-s-1vcpu-0.5gb` (~$5/mo)  
**Scales to zero:** No (Basic tier keeps 1 instance running)

### Deploy via spec file

```bash
# Install doctl if needed
brew install doctl
doctl auth init

# Create the app from the spec
doctl apps create --spec do-app-spec.yml

# Set secrets (MODEL_ACCESS_KEY, N8N_WEBHOOK_URL)
doctl apps update <app-id> --spec do-app-spec.yml
```

Or via the DO Dashboard:
1. **Create App** → **GitHub** → repo `chelstein/avr-infra` → branch `main`
2. Source dir: `vela-adapter`, Dockerfile: `vela-adapter/Dockerfile`
3. Set environment variables / secrets in the UI
4. HTTP port: `8088`, health check: `/healthz`

### After deployment

The App Platform will give you a public URL like:  
`https://vela-adapter-xxxxx.ondigitalocean.app`

Use this URL when configuring Asterisk/AVR to POST transcripts to `/intake/voice`.

---

## Resource 3: AVR + n8n Droplet

**Product:** DO Droplet  
**Recommended size:** `s-2vcpu-4gb` (~$24/mo)  
**OS:** Ubuntu 24.04 LTS

The existing AVR stack (Asterisk, avr-core, ASR/TTS services) and n8n run best on a Droplet because:
- Asterisk requires raw UDP port access (SIP 5060, RTP 10000–10050)
- n8n needs a persistent volume for workflow and credential storage
- The AVR services communicate over a private Docker network

### Recommended Droplet spec

| Property | Value |
|---|---|
| Size | `s-2vcpu-4gb` |
| Region | `nyc3` (or match your App Platform region) |
| OS | Ubuntu 24.04 LTS |
| SSH key | Your team key |
| Firewall | See below |

### Required firewall rules (inbound)

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | Your IP | SSH |
| 80 | TCP | Any | Traefik HTTP (if using avr-app) |
| 443 | TCP | Any | Traefik HTTPS |
| 5060 | UDP | Any | SIP signaling |
| 8089 | TCP | Any | Asterisk WebSocket (WebRTC) |
| 5678 | TCP | App Platform egress | n8n webhook inbound |
| 10000–10050 | UDP | Any | RTP media |

### Bootstrap commands

```bash
# SSH into the Droplet
ssh root@<droplet-ip>

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# Clone the repo
git clone https://github.com/chelstein/avr-infra.git
cd avr-infra
cp .env.example .env
# Edit .env with your keys

# Start the AVR stack (choose a compose file)
docker compose -f docker-compose-openai.yml up -d

# Start n8n
docker compose -f docker-compose-n8n.yml up -d
```

### n8n Persistent Storage

The `docker-compose-n8n.yml` already mounts `./n8n:/home/node/.n8n`.  
For safety, also attach a **DO Volume** (block storage) and mount it at `/root/avr-infra/n8n`:

```bash
# Create a 10 GB volume and attach to Droplet via DO Dashboard
# Then mount it
mkdir -p /mnt/n8n-data
mount /dev/disk/by-id/scsi-0DO_Volume_<volume-id> /mnt/n8n-data
ln -sf /mnt/n8n-data /root/avr-infra/n8n
```

---

## Networking: Connecting App Platform ↔ Droplet

App Platform services cannot join a Droplet's private network directly. Use one of:

1. **Public HTTPS** (simplest for PoC): App Platform calls n8n webhook via public URL. Firewall allows inbound 5678 from App Platform egress IPs.

2. **DO Managed VPC + Droplet private IP** (recommended for production): Place Droplet in a VPC. App Platform services can reach it via the Droplet's private IP if they're in the same region.

3. **Reverse proxy on Droplet**: Run Traefik or nginx on the Droplet with TLS termination; expose n8n at `https://n8n.yourdomain.com`.

---

## Summary: What to Provision

| # | Resource | DO Product | Size | ~Cost/mo |
|---|---|---|---|---|
| 1 | DO Inference API key | GenAI Platform | Serverless | Pay-per-token |
| 2 | vela-adapter | App Platform | `apps-s-1vcpu-0.5gb` | ~$5 |
| 3 | AVR + n8n | Droplet | `s-2vcpu-4gb` | ~$24 |
| 4 | n8n storage | Volume (block storage) | 10 GB | ~$1 |
| **Total** | | | | **~$30/mo** |

### Optional for production

| Resource | Purpose | Cost |
|---|---|---|
| DO Managed PostgreSQL | Replace n8n SQLite for HA | ~$15/mo |
| DO Load Balancer | HA for App Platform (built-in) | Included |
| DO Spaces | Store call recordings | ~$5/mo + transfer |
