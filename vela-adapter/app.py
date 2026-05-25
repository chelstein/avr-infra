import os
import json
import logging
import httpx
from collections import deque
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Vela Adapter", version="0.2.0")

MODEL_ACCESS_KEY    = os.environ.get("MODEL_ACCESS_KEY", "")
N8N_WEBHOOK_URL     = os.environ.get("N8N_WEBHOOK_URL", "")
DO_INFERENCE_BASE_URL = os.environ.get("DO_INFERENCE_BASE_URL", "https://inference.do-ai.run/v1")
DO_INFERENCE_MODEL  = os.environ.get("DO_INFERENCE_MODEL", "router:gmi-service-desk")
DEEPGRAM_API_KEY    = os.environ.get("DEEPGRAM_API_KEY", "")
DEEPGRAM_BASE_URL   = "https://api.deepgram.com/v1"

# In-memory call log — last 100 calls
call_log: deque = deque(maxlen=100)

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


class RecordingIntakeRequest(BaseModel):
    channel: str = "voice"
    provider: str = "freepbx"
    session_id: str = ""
    caller_id: str = ""
    called_number: str = ""
    recording_url: str = ""


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "service": "vela-adapter",
        "version": "0.2.0",
        "calls_processed": len(call_log),
        "deepgram": "configured" if DEEPGRAM_API_KEY else "missing",
    }


@app.get("/calls")
async def get_calls():
    return {"calls": list(reversed(list(call_log))), "total": len(call_log)}


async def _transcribe_recording(recording_url: str) -> str:
    """Transcribe an audio file URL via Deepgram Nova 3."""
    if not DEEPGRAM_API_KEY:
        raise HTTPException(status_code=503, detail="DEEPGRAM_API_KEY not configured")

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }
    params = "model=nova-3&smart_format=true&punctuate=true&diarize=true"

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(
                f"{DEEPGRAM_BASE_URL}/listen?{params}",
                headers=headers,
                json={"url": recording_url},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("Deepgram error %s: %s", e.response.status_code, e.response.text)
            raise HTTPException(status_code=502, detail=f"Transcription error: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error("Deepgram unreachable: %s", e)
            raise HTTPException(status_code=502, detail="Transcription service unreachable")

    data = resp.json()
    try:
        transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError):
        logger.error("Unexpected Deepgram response: %s", data)
        raise HTTPException(status_code=502, detail="Unexpected transcription response format")

    if not transcript.strip():
        raise HTTPException(status_code=422, detail="No speech detected in recording")

    logger.info("Deepgram transcribed %d chars from %s", len(transcript), recording_url)
    return transcript


@app.post("/intake/recording")
async def intake_recording(payload: RecordingIntakeRequest):
    """Accept a FreePBX recording URL, transcribe it, then classify via DO Inference."""
    if not payload.recording_url:
        raise HTTPException(status_code=400, detail="recording_url is required")

    transcript = await _transcribe_recording(payload.recording_url)

    voice_payload = VoiceIntakeRequest(
        channel=payload.channel,
        provider=payload.provider,
        session_id=payload.session_id,
        caller_id=payload.caller_id,
        called_number=payload.called_number,
        raw_transcript=transcript,
        recording_url=payload.recording_url,
    )
    return await intake_voice(voice_payload)


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

    for field in ("channel", "provider", "session_id", "caller_id", "called_number", "raw_transcript"):
        normalized.setdefault(field, getattr(payload, field))

    # Normalize confidence to 0.0–1.0; model sometimes returns 0–100 integer
    if "workflow_decision" in normalized:
        conf = normalized["workflow_decision"].get("confidence", 0)
        if isinstance(conf, (int, float)) and conf > 1:
            normalized["workflow_decision"]["confidence"] = round(conf / 100, 4)

    normalized["_received_at"] = datetime.now(timezone.utc).isoformat()
    call_log.append(normalized)

    if N8N_WEBHOOK_URL:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                n8n_resp = await client.post(N8N_WEBHOOK_URL, json=normalized)
                n8n_resp.raise_for_status()
                logger.info("n8n webhook delivered, status=%s", n8n_resp.status_code)
            except httpx.HTTPStatusError as e:
                logger.warning("n8n webhook error %s: %s", e.response.status_code, e.response.text)
            except httpx.RequestError as e:
                logger.warning("n8n webhook unreachable: %s", e)
    else:
        logger.warning("N8N_WEBHOOK_URL not set — skipping webhook delivery")

    return normalized


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vela — AI Intake Monitor</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #e6edf3; font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 24px; background: #161b22;
    border-bottom: 1px solid #30363d;
  }
  .logo { font-size: 20px; font-weight: 700; letter-spacing: 2px; color: #58a6ff; }
  .logo span { color: #e6edf3; font-weight: 300; }
  .live-badge {
    display: flex; align-items: center; gap: 6px;
    font-size: 12px; color: #3fb950; font-weight: 600; letter-spacing: 1px;
  }
  .live-dot { width: 8px; height: 8px; background: #3fb950; border-radius: 50%; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }

  .stats {
    display: flex; gap: 0; border-bottom: 1px solid #30363d;
  }
  .stat {
    flex: 1; padding: 16px 24px; border-right: 1px solid #30363d;
    display: flex; flex-direction: column; gap: 4px;
  }
  .stat:last-child { border-right: none; }
  .stat-label { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
  .stat-value { font-size: 28px; font-weight: 700; }
  .stat-value.blue  { color: #58a6ff; }
  .stat-value.red   { color: #f85149; }
  .stat-value.green { color: #3fb950; }
  .stat-value.orange{ color: #d29922; }

  .queue { padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; }
  .queue-header { font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }

  .empty { text-align: center; padding: 60px; color: #8b949e; }
  .empty-icon { font-size: 48px; margin-bottom: 12px; }
  .empty-text { font-size: 14px; }

  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px 20px; display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 0 16px; align-items: start;
    animation: slideIn .3s ease;
  }
  @keyframes slideIn { from{opacity:0;transform:translateY(-8px)} to{opacity:1;transform:none} }

  .card-accent { width: 4px; border-radius: 2px; align-self: stretch; min-height: 60px; }
  .accent-critical { background: #f85149; }
  .accent-high     { background: #d29922; }
  .accent-medium   { background: #58a6ff; }
  .accent-low      { background: #3fb950; }
  .accent-unknown  { background: #8b949e; }

  .card-body { min-width: 0; }
  .card-top { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; flex-wrap: wrap; }
  .caller { font-size: 15px; font-weight: 600; color: #e6edf3; }
  .time   { font-size: 11px; color: #8b949e; margin-left: auto; white-space: nowrap; }

  .badge {
    font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 10px;
    text-transform: uppercase; letter-spacing: .5px;
  }
  .badge-handoff  { background: #f8514920; color: #f85149; border: 1px solid #f8514940; }
  .badge-auto     { background: #3fb95020; color: #3fb950; border: 1px solid #3fb95040; }
  .badge-idverify { background: #d2992220; color: #d29922; border: 1px solid #d2992240; }
  .badge-critical { background: #f8514920; color: #f85149; border: 1px solid #f8514940; }
  .badge-high     { background: #d2992220; color: #d29922; border: 1px solid #d2992240; }
  .badge-medium   { background: #58a6ff20; color: #58a6ff; border: 1px solid #58a6ff40; }
  .badge-low      { background: #3fb95020; color: #3fb950; border: 1px solid #3fb95040; }

  .summary { font-size: 14px; color: #c9d1d9; margin-bottom: 8px; line-height: 1.4; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; color: #8b949e; }
  .meta-item { display: flex; gap: 4px; }
  .meta-key { color: #8b949e; }
  .meta-val { color: #c9d1d9; }

  .card-right { text-align: right; min-width: 80px; }
  .confidence { font-size: 22px; font-weight: 700; }
  .conf-label { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: .5px; }
  .conf-high   { color: #3fb950; }
  .conf-medium { color: #d29922; }
  .conf-low    { color: #f85149; }

  .next-action {
    margin-top: 10px; padding: 10px 14px;
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    font-size: 12px; color: #8b949e; line-height: 1.5;
    grid-column: 2 / 4;
  }
  .next-action strong { color: #58a6ff; }

  .transcript-toggle {
    margin-top: 8px; font-size: 11px; color: #58a6ff;
    cursor: pointer; user-select: none;
    grid-column: 2 / 4;
  }
  .transcript {
    margin-top: 6px; padding: 10px 14px;
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    font-size: 12px; color: #8b949e; font-style: italic; line-height: 1.5;
    grid-column: 2 / 4;
    display: none;
  }

  footer { padding: 16px 24px; border-top: 1px solid #30363d; font-size: 11px; color: #8b949e; text-align: center; }
</style>
</head>
<body>
<header>
  <div class="logo">VELA <span>AI INTAKE MONITOR</span></div>
  <div class="live-badge"><div class="live-dot"></div> LIVE — refreshes every 5s</div>
</header>

<div class="stats">
  <div class="stat"><div class="stat-label">Total Calls</div><div class="stat-value blue" id="s-total">—</div></div>
  <div class="stat"><div class="stat-label">Human Handoff</div><div class="stat-value red" id="s-handoff">—</div></div>
  <div class="stat"><div class="stat-label">Auto-Eligible</div><div class="stat-value green" id="s-auto">—</div></div>
  <div class="stat"><div class="stat-label">ID Verify Needed</div><div class="stat-value orange" id="s-idv">—</div></div>
  <div class="stat"><div class="stat-label">Avg Confidence</div><div class="stat-value blue" id="s-conf">—</div></div>
</div>

<div class="queue">
  <div class="queue-header">Recent Calls — newest first</div>
  <div id="cards"><div class="empty"><div class="empty-icon">&#9743;</div><div class="empty-text">No calls yet. POST a recording URL to /intake/recording or a transcript to /intake/voice.</div></div></div>
</div>

<footer>vela-adapter v0.2.0 &bull; router:gmi-service-desk &bull; Deepgram Nova 3 &bull; <a href="/calls" style="color:#58a6ff">JSON API</a> &bull; <a href="/healthz" style="color:#58a6ff">Health</a></footer>

<script>
function urgencyClass(u) {
  if (!u) return 'unknown';
  const l = u.toLowerCase();
  if (l.includes('critical')) return 'critical';
  if (l.includes('high'))     return 'high';
  if (l.includes('medium'))   return 'medium';
  return 'low';
}
function confClass(c) {
  if (c >= 0.8) return 'conf-high';
  if (c >= 0.6) return 'conf-medium';
  return 'conf-low';
}
function timeAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60)  return s + 's ago';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  return Math.floor(s/3600) + 'h ago';
}
function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function refresh() {
  let data;
  try { data = await fetch('/calls').then(r=>r.json()); } catch(e) { return; }
  const calls = data.calls || [];

  const handoff = calls.filter(c=>c.workflow_decision?.human_handoff_required).length;
  const autoE   = calls.filter(c=>c.ticket_fields?.automation_eligible).length;
  const idv     = calls.filter(c=>c.workflow_decision?.identity_verification_required).length;
  const avgConf = calls.length ? (calls.reduce((a,c)=>a+Math.min(1, c.workflow_decision?.confidence||0),0)/calls.length) : 0;
  document.getElementById('s-total').textContent   = calls.length;
  document.getElementById('s-handoff').textContent = handoff;
  document.getElementById('s-auto').textContent    = autoE;
  document.getElementById('s-idv').textContent     = idv;
  document.getElementById('s-conf').textContent    = calls.length ? (avgConf*100).toFixed(0)+'%' : '—';

  if (!calls.length) {
    document.getElementById('cards').innerHTML = '<div class="empty"><div class="empty-icon">&#9743;</div><div class="empty-text">No calls yet. POST a recording URL to /intake/recording or a transcript to /intake/voice.</div></div>';
    return;
  }

  const html = calls.map((c) => {
    const tf  = c.ticket_fields || {};
    const wd  = c.workflow_decision || {};
    const urg = urgencyClass(tf.urgency);
    const conf = Math.min(1, wd.confidence || 0);
    const confPct = (conf * 100).toFixed(0) + '%';
    const badges = [];
    if (wd.human_handoff_required)        badges.push('<span class="badge badge-handoff">&#128222; Handoff</span>');
    if (tf.automation_eligible)            badges.push('<span class="badge badge-auto">&#9889; Auto</span>');
    if (wd.identity_verification_required) badges.push('<span class="badge badge-idverify">&#128274; ID Verify</span>');
    if (tf.urgency) badges.push('<span class="badge badge-'+urg+'">'+escHtml(tf.urgency)+'</span>');

    const metaItems = [
      tf.category       ? ['Category',  tf.category]       : null,
      tf.subcategory    ? ['Sub',       tf.subcategory]     : null,
      tf.affected_system? ['System',   tf.affected_system] : null,
      tf.sentiment      ? ['Sentiment', tf.sentiment]       : null,
      tf.recommended_assignment_group ? ['Assign', tf.recommended_assignment_group] : null,
    ].filter(Boolean).slice(0,5);

    const metaHtml = metaItems.map(([k,v])=>`<span class="meta-item"><span class="meta-key">${escHtml(k)}:</span><span class="meta-val">${escHtml(v)}</span></span>`).join('');
    const ts = c._received_at ? timeAgo(c._received_at) : '';
    const src = c.provider === 'freepbx' ? ' &#127925;' : '';

    return `
    <div class="card">
      <div class="card-accent accent-${urg}"></div>
      <div class="card-body">
        <div class="card-top">
          <span class="caller">${escHtml(c.caller_id || 'Unknown')}${src}</span>
          ${badges.join('')}
          <span class="time">${escHtml(ts)}</span>
        </div>
        <div class="summary">${escHtml(c.summary || tf.issue_summary || c.raw_transcript?.slice(0,120))}</div>
        <div class="meta">${metaHtml}</div>
      </div>
      <div class="card-right">
        <div class="confidence ${confClass(conf)}">${confPct}</div>
        <div class="conf-label">Confidence</div>
      </div>
      ${tf.suggested_next_action ? `<div class="next-action"><strong>&#9658; Next:</strong> ${escHtml(tf.suggested_next_action)}</div>` : ''}
      <div class="transcript-toggle" onclick="var t=this.nextElementSibling;t.style.display=t.style.display==='block'?'none':'block';this.textContent=t.style.display==='block'?'▲ Hide transcript':'▼ Show transcript'">&#9660; Show transcript</div>
      <div class="transcript">${escHtml(c.raw_transcript)}</div>
    </div>`;
  }).join('');

  document.getElementById('cards').innerHTML = html;
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=DASHBOARD_HTML)
