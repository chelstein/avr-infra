# Vela Architecture

## Overview

Vela is a reusable AI voice intake spine that sits between the AVR telephony stack and downstream service desk workflows. It normalizes raw call transcripts into structured ticket data using DigitalOcean Serverless Inference.

## Core Flow

```
Asterisk/AVR voice call
    │
    ▼  POST /intake/voice
vela-adapter
    │
    ├─► DO Inference Router (router:gmi-service-desk)
    │       └─► returns normalized service desk JSON
    │
    └─► n8n webhook  (POST normalized payload)
            │
            ├─► [placeholder] ConnectWise ticket
            ├─► [placeholder] SharePoint log
            └─► [placeholder] Webex notification
```

## Services

| Service | Port | Role |
|---|---|---|
| `avr-asterisk` | 8088/8089, 5060 | PBX / SIP / WebRTC gateway |
| `avr-core` | 5001 | Voice pipeline orchestrator (ASR→LLM→TTS) |
| `avr-asr-*` | 6010+ | Automatic Speech Recognition |
| `avr-llm-*` | 6002/6016+ | LLM response generation (interactive calls) |
| `avr-tts-*` | 6011+ | Text-to-Speech synthesis |
| `avr-ami` | 6006 | Asterisk Manager Interface bridge |
| `vela-adapter` | 8088 | Service desk intake normalizer (this service) |

## How Transcripts Move Through the System

### Real-time AVR path (interactive calls)
1. Caller dials in via SIP or WebRTC → **Asterisk**
2. Asterisk routes via ARI to **avr-core**
3. avr-core streams audio to **ASR service** → transcript segments
4. Transcript sent to **LLM service** → response text
5. Response piped to **TTS service** → synthesized audio
6. Audio played back to caller via Asterisk

### Vela intake path (post-call or in-parallel)
1. When a call ends (or at any point), the raw transcript is POSTed to **vela-adapter `/intake/voice`**
2. vela-adapter sends a structured prompt + transcript to **DO Inference** (`router:gmi-service-desk`)
3. The router returns a normalized JSON payload with ticket fields, workflow decisions, and sentiment
4. vela-adapter forwards the payload to the configured **n8n webhook**
5. n8n routes the payload to ConnectWise, SharePoint, Webex, or other targets

## Where ASR/LLM/TTS Happens

| Stage | Service image | Protocol |
|---|---|---|
| ASR | `agentvoiceresponse/avr-asr-deepgram` (or alternatives) | `/speech-to-text-stream` (streaming) |
| LLM | `agentvoiceresponse/avr-llm-openai` (or alternatives) | `/prompt-stream` (streaming) |
| TTS | `agentvoiceresponse/avr-tts-deepgram` (or alternatives) | `/text-to-speech-stream` (streaming) |
| Intake NLU | DigitalOcean Inference `router:gmi-service-desk` | OpenAI-compatible REST API |

## Environment Variables

| Variable | Purpose |
|---|---|
| `MODEL_ACCESS_KEY` | DigitalOcean Inference API key |
| `DO_INFERENCE_BASE_URL` | Base URL for DO Inference (default: `https://inference.do-ai.run/v1`) |
| `DO_INFERENCE_MODEL` | Model identifier (default: `router:gmi-service-desk`) |
| `N8N_WEBHOOK_URL` | n8n webhook endpoint to deliver normalized payload |
| `VELA_ADAPTER_PORT` | Port the service listens on (default: `8088`) |

## Placeholders (not yet implemented)

- **ConnectWise**: n8n will create tickets — no direct integration in vela-adapter
- **SharePoint**: n8n will log calls — no direct integration in vela-adapter
- **Webex**: n8n will send notifications — no direct integration in vela-adapter

These are intentionally deferred to n8n workflow nodes.
