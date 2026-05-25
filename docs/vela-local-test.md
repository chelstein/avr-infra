# Running Vela Adapter Locally

## Prerequisites

- Docker and Docker Compose
- A DigitalOcean Inference API key (`MODEL_ACCESS_KEY`)
- (Optional) n8n instance with a webhook URL

## 1. Configure Environment

```bash
cp .env.example .env
```

Minimum required vars for vela-adapter:

```env
MODEL_ACCESS_KEY=your_do_inference_key
DO_INFERENCE_BASE_URL=https://inference.do-ai.run/v1
DO_INFERENCE_MODEL=router:gmi-service-desk
N8N_WEBHOOK_URL=http://avr-n8n:5678/webhook/your-webhook-id
VELA_ADAPTER_PORT=8088
```

## 2. Build and Start

**Standalone (no existing AVR stack):**

```bash
docker compose -f docker-compose-vela.yml up --build
```

**Alongside the AVR stack** (recommended — shares the `avr` Docker network):

```bash
# Start the main AVR stack first
docker compose -f docker-compose-app.yml up -d

# Then add vela-adapter
docker compose -f docker-compose-vela.yml up --build -d
```

> **Note:** `docker-compose-vela.yml` declares the `avr` network as `external: true`.
> The AVR stack must be running first so the network exists.

## 3. Verify Health

```bash
curl http://localhost:8088/healthz
# Expected: {"status":"ok","service":"vela-adapter"}
```

## 4. Test with a Voice Intake

```bash
curl -X POST http://localhost:8088/intake/voice \
  -H "Content-Type: application/json" \
  -d '{
    "channel":"voice",
    "provider":"asterisk",
    "session_id":"test-001",
    "caller_id":"+15555550123",
    "called_number":"+15555550999",
    "raw_transcript":"Hi, my VPN stopped working after I changed my password and now Outlook will not connect.",
    "recording_url":""
  }'
```

Expected response: a fully populated JSON object with `ticket_fields` and `workflow_decision`.

## 5. View Logs

```bash
docker logs -f vela-adapter
```

---

## Wiring Asterisk/AVR Transcript Events into /intake/voice

When a call ends in AVR, the raw transcript accumulated by `avr-core` (via the ASR stream) needs to be submitted to vela-adapter. Three integration paths:

### Option A — Custom LLM tool function

Add a tool in `./tools/` that the `avr-llm-*` service calls at end-of-session. The tool POSTs the full accumulated transcript to `http://vela-adapter:8088/intake/voice`. This keeps the integration entirely within the AVR container network.

### Option B — n8n AMI/ARI trigger

Configure an n8n workflow triggered by an Asterisk `Hangup` AMI event (via `avr-ami`). The workflow collects the call transcript from a recording or transcript store and POSTs it to `http://vela-adapter:8088/intake/voice`.

### Option C — Asterisk dialplan AGI/ARI

Use an AGI script or ARI application stasis handler called at hangup to HTTP POST the transcript to the vela-adapter URL. Requires customizing `asterisk/conf/extensions.conf`.

**Recommended for PoC:** Option B (n8n AMI trigger) — no code changes to existing AVR services required.
