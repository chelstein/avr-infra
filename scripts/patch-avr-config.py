#!/usr/bin/env python3
"""Patch /opt/avr/config/ai-agent.yaml for Vela GMI service desk integration."""
import re, sys

YAML_PATH = '/opt/avr/config/ai-agent.yaml'

try:
    with open(YAML_PATH) as f:
        yaml = f.read()
except FileNotFoundError:
    print(f'ERROR: {YAML_PATH} not found')
    sys.exit(1)

changes = 0

# 1. Update default context: change provider to deepgram, update greeting/prompt, add post_call_tools
old_default = '''  default:
    greeting: Hello
    profile: telephony_ulaw_8k
    prompt: >-
      You are Asterisk, an AI Assistant. Be helpful and concise.


      CALL ENDING:
      - When the caller indicates they are done, say a brief farewell, then use the hangup_call tool to end the call.
      - NEVER mention tools or the word "hangup_call" to the caller.
    provider: local
    tools:
      - hangup_call'''

new_default = '''  default:
    greeting: "Thank you for calling GMI service desk. I'm Vela, your AI assistant. What can I help you with today?"
    profile: telephony_ulaw_8k
    prompt: >-
      You are Vela, an AI service desk intake specialist for GMI. Gather information about the caller\'s IT issue.

      Ask about:
      - The caller\'s name and callback number
      - What system or device is affected and what the issue is
      - When the issue started and any troubleshooting already attempted

      Be concise and professional. Once you have the key details, thank the caller and let them know a technician will follow up.

      CALL ENDING:
      - When you have gathered the necessary information, say a brief farewell and use the hangup_call tool to end the call.
      - NEVER mention tools or the word "hangup_call" to the caller.
    provider: deepgram
    tools:
      - hangup_call
    post_call_tools:
      - vela_intake'''

if old_default in yaml:
    yaml = yaml.replace(old_default, new_default, 1)
    changes += 1
    print('OK: updated default context')
elif 'provider: deepgram' in yaml and 'vela_intake' in yaml:
    print('SKIP: default context already patched')
else:
    print('WARN: default context pattern not found - may need manual edit')

# 2. Enable deepgram provider
old_dg = '    continuous_input: true\n    enabled: false\n    greeting: Hello, how can I help you today?'
new_dg = '    continuous_input: true\n    enabled: true\n    greeting: "Thank you for calling GMI service desk. I\'m Vela, your AI assistant. What can I help you with today?"'

if old_dg in yaml:
    yaml = yaml.replace(old_dg, new_dg, 1)
    changes += 1
    print('OK: enabled deepgram provider')
else:
    print('SKIP: deepgram already enabled or pattern changed')

# 3. Update deepgram instructions
old_instr = '    instructions: Voice assistant. Answer in 5-8 words. Be direct. Expand only if asked.'
new_instr = '    instructions: "You are Vela, a GMI service desk intake specialist. Gather the caller name, issue description, affected system, and any troubleshooting attempted. Be concise and professional."'

if old_instr in yaml:
    yaml = yaml.replace(old_instr, new_instr, 1)
    changes += 1
    print('OK: updated deepgram instructions')
else:
    print('SKIP: deepgram instructions already updated or pattern changed')

# 4. Add vela_intake tool before sample_discord_post_call_webhook
vela_tool = '''  vela_intake:
    kind: generic_webhook
    phase: post_call
    enabled: true
    is_global: false
    timeout_ms: 15000
    url: "https://vela-adapter-rs4hj.ondigitalocean.app/intake/voice"
    method: POST
    headers:
      Content-Type: "application/json"
    payload_template: |
      {
        "caller_id": "{caller_number}",
        "called_number": "{called_number}",
        "session_id": "{call_id}",
        "raw_transcript": "{summary}",
        "provider": "freepbx-avr",
        "channel": "voice"
      }
    generate_summary: true

  '''

if 'vela_intake:' not in yaml:
    yaml = yaml.replace('  sample_discord_post_call_webhook:', vela_tool + '  sample_discord_post_call_webhook:', 1)
    changes += 1
    print('OK: added vela_intake webhook tool')
else:
    print('SKIP: vela_intake already present')

with open(YAML_PATH, 'w') as f:
    f.write(yaml)

print(f'\nDone. {changes} changes applied to {YAML_PATH}')
