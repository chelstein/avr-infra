#!/bin/bash
set -e
cd /opt/avr

cat > .env << 'ENVEOF'
COMPOSE_PROJECT_NAME=asterisk-ai-voice-agent
HOST_PROJECT_ROOT=/opt/avr
ASTERISK_HOST=127.0.0.1
ASTERISK_ARI_PORT=8088
ASTERISK_ARI_USERNAME=avr
ASTERISK_ARI_PASSWORD=Avr2026Secret
OPENAI_API_KEY=PLACEHOLDER_OPENAI
DEEPGRAM_API_KEY=PLACEHOLDER_DEEPGRAM
CALL_HISTORY_ENABLED=true
ASTERISK_RECORDING_PATH=/var/spool/asterisk/monitor
ENVEOF

sed -i "s/PLACEHOLDER_OPENAI/${OPENAI_KEY}/" .env
sed -i "s/PLACEHOLDER_DEEPGRAM/${DEEPGRAM_KEY}/" .env

mkdir -p asterisk_media

echo "Done! .env created:"
grep -v KEY .env
echo "(API keys hidden)"
