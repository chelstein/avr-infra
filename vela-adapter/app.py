import os
import json
import logging
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Vela Adapter", version="0.1.0")

MODEL_ACCESS_KEY = os.environ.get("MODEL_ACCESS_KEY", "")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
DO_INFERENCE_BASE_URL = os.environ.get("DO_INFERENCE_BASE_URL", "https://inference.do-ai.run/v1")
DO_INFERENCE_MODEL = os.environ.get("DO_INFERENCE_MODEL", "router:gmi-service-desk")

SYSTEM_PROMPT = """You are a service desk intake classifier. Analyze the voice call transcript and return structured ticket data.
Respond with ONLY valid JSON — no markdown fences, no explanation — matching this exact schema:

{
  "channel": "",
  "provider": "",
  "session_id": "",
  "caller_id": "",
  "called_number": "",
  "raw_transcript": "",
  "summary": "",
  "ticket_fields": {
    "requester": "",
    "callback": "",
    "issue_summary": "",
    "category": "",
    "subcategory": "",
    "urgency": "",
    "impact": "",
    "affected_system": "",
    "affected_device": "",
    "operating_system": "",
    "business_service": "",
    "location": "",
    "troubleshooting_attempted": [],
    "sentiment": "",
    "recommended_assignment_group": "",
    "automation_eligible": false,
    "escalation_indicators": [],
    "suggested_next_action": ""
  },
  "workflow_decision": {
    "recommended_workflow": "",
    "human_handoff_required": false,
    "identity_verification_required": false,
    "confidence": 0
  }
}"""


class VoiceIntakeRequest(BaseModel):
    channel: str = "voice"
    provider: str = "asterisk"
    session_id: str = ""
    caller_id: str = ""
    called_number: str = ""
    raw_transcript: str = ""
    recording_url: str = ""


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "vela-adapter"}


@app.post("/intake/voice")
async def intake_voice(payload: VoiceIntakeRequest):
    if not payload.raw_transcript:
        raise HTTPException(status_code=400, detail="raw_transcript is required")

    user_message = (
        f"Channel: {payload.channel}\n"
        f"Provider: {payload.provider}\n"
        f"Session ID: {payload.session_id}\n"
        f"Caller ID: {payload.caller_id}\n"
        f"Called Number: {payload.called_number}\n"
        f"Recording URL: {payload.recording_url}\n\n"
        f"Transcript:\n{payload.raw_transcript}"
    )

    headers = {
        "Authorization": f"Bearer {MODEL_ACCESS_KEY}",
        "Content-Type": "application/json",
    }
    inference_body = {
        "model": DO_INFERENCE_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                f"{DO_INFERENCE_BASE_URL}/chat/completions",
                headers=headers,
                json=inference_body,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("DO Inference error %s: %s", e.response.status_code, e.response.text)
            raise HTTPException(
                status_code=502,
                detail=f"Inference service error: {e.response.status_code}",
            )
        except httpx.RequestError as e:
            logger.error("DO Inference unreachable: %s", e)
            raise HTTPException(status_code=502, detail="Inference service unreachable")

    raw_content = resp.json()["choices"][0]["message"]["content"]
    try:
        normalized = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.error("Inference returned non-JSON: %s", raw_content)
        raise HTTPException(status_code=502, detail="Inference returned invalid JSON")

    # Ensure input metadata is always present even if model omits fields
    for field in ("channel", "provider", "session_id", "caller_id", "called_number", "raw_transcript"):
        normalized.setdefault(field, getattr(payload, field))

    if N8N_WEBHOOK_URL:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                n8n_resp = await client.post(N8N_WEBHOOK_URL, json=normalized)
                n8n_resp.raise_for_status()
                logger.info("n8n webhook delivered, status=%s", n8n_resp.status_code)
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "n8n webhook error %s: %s", e.response.status_code, e.response.text
                )
            except httpx.RequestError as e:
                logger.warning("n8n webhook unreachable: %s", e)
    else:
        logger.warning("N8N_WEBHOOK_URL not set — skipping webhook delivery")

    return normalized
