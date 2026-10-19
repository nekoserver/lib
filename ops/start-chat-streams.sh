#!/bin/bash
set -eu
# Preserve both HMAC config files; each service validates against both.
set -a
[ ! -f /etc/lib-hmac.env ] || . /etc/lib-hmac.env
[ ! -f /etc/lib-chat.env ] || . /etc/lib-chat.env
set +a
PYTHONPATH=/var/www/html/lib/ops runuser -u www-data -- /opt/lib-chat/bin/python -c 'from chat_hmac import load_secret; load_secret()'
for stream in chat_websocket chat_http_stream; do
    pidfile=/run/lib-${stream}.pid
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then continue; fi
    nohup setsid runuser -u www-data -- /opt/lib-chat/bin/python /var/www/html/lib/ops/${stream}.py >>/var/log/lib-${stream}.log 2>&1 < /dev/null &
    echo $! > "$pidfile"
done
