# Vela → n8n Webhook Payload

## Overview

After each successful call intake, `vela-adapter` POSTs a normalized JSON payload to the URL configured in `N8N_WEBHOOK_URL`.

## HTTP Request

```
POST {N8N_WEBHOOK_URL}
Content-Type: application/json
```

## Example Payload

```json
{
  "channel": "voice",
  "provider": "asterisk",
  "session_id": "test-001",
  "caller_id": "+15555550123",
  "called_number": "+15555550999",
  "raw_transcript": "Hi, my VPN stopped working after I changed my password and now Outlook will not connect.",
  "summary": "Caller reports VPN failure and Outlook connectivity issue following a password change.",
  "ticket_fields": {
    "requester": "+15555550123",
    "callback": "+15555550123",
    "issue_summary": "VPN stopped working after password change; Outlook cannot connect",
    "category": "Network",
    "subcategory": "VPN",
    "urgency": "High",
    "impact": "User",
    "affected_system": "VPN, Outlook",
    "affected_device": "",
    "operating_system": "",
    "business_service": "",
    "location": "",
    "troubleshooting_attempted": [],
    "sentiment": "frustrated",
    "recommended_assignment_group": "Network Engineering",
    "automation_eligible": false,
    "escalation_indicators": ["authentication_failure", "multi_system_impact"],
    "suggested_next_action": "Reset VPN credentials and verify Outlook profile authentication"
  },
  "workflow_decision": {
    "recommended_workflow": "password_reset_and_vpn_reconnect",
    "human_handoff_required": false,
    "identity_verification_required": true,
    "confidence": 0.87
  }
}
```

## Field Reference

### Top-level

| Field | Type | Description |
|---|---|---|
| `channel` | string | Always `"voice"` for voice calls |
| `provider` | string | Source system (`"asterisk"`) |
| `session_id` | string | Unique call session ID |
| `caller_id` | string | ANI / caller phone number |
| `called_number` | string | DNIS / dialed number |
| `raw_transcript` | string | Verbatim transcript from ASR |
| `summary` | string | AI-generated one-sentence summary |

### ticket_fields

| Field | Type | Description |
|---|---|---|
| `requester` | string | Best-guess requester identity |
| `callback` | string | Phone number for callback |
| `issue_summary` | string | Brief description of the issue |
| `category` | string | Top-level ITSM category |
| `subcategory` | string | ITSM subcategory |
| `urgency` | string | `Low` / `Medium` / `High` / `Critical` |
| `impact` | string | `User` / `Department` / `Business` |
| `affected_system` | string | System or application name |
| `affected_device` | string | Device hostname or type |
| `operating_system` | string | OS of affected device |
| `business_service` | string | Business service affected |
| `location` | string | Office / site / remote |
| `troubleshooting_attempted` | array | Steps already tried by caller |
| `sentiment` | string | Caller sentiment (`calm` / `frustrated` / `urgent`) |
| `recommended_assignment_group` | string | Suggested team to handle the ticket |
| `automation_eligible` | boolean | Can this be auto-resolved? |
| `escalation_indicators` | array | Signals that warrant escalation |
| `suggested_next_action` | string | Recommended next step |

### workflow_decision

| Field | Type | Description |
|---|---|---|
| `recommended_workflow` | string | n8n workflow to trigger |
| `human_handoff_required` | boolean | Needs live agent? |
| `identity_verification_required` | boolean | Must verify caller identity? |
| `confidence` | number | Model confidence (0–1) |

## n8n Workflow Design Notes

In n8n, create a **Webhook** node as the trigger (HTTP method: `POST`). The payload arrives in `$json`. Example expressions:

```js
// Get issue summary
{{ $json.ticket_fields.issue_summary }}

// Check if human handoff is needed
{{ $json.workflow_decision.human_handoff_required }}

// Route based on recommended workflow
{{ $json.workflow_decision.recommended_workflow }}
```

### Suggested n8n Flow

```
Webhook (POST)
  └─ IF human_handoff_required == true
      └─ [placeholder] Notify live agent (Webex / email)
  └─ IF automation_eligible == true
      └─ [placeholder] Run auto-resolve workflow
  └─ [placeholder] Create ConnectWise ticket
  └─ [placeholder] Log to SharePoint list
```

### Placeholder Integrations (not yet implemented)

| Target | Node Type | Notes |
|---|---|---|
| ConnectWise | HTTP Request | POST to CW Manage REST API |
| SharePoint | Microsoft SharePoint node | Append row to list |
| Webex | HTTP Request | POST to Webex messaging API |
