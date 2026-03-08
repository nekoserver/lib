#!/bin/bash
echo "Content-Type: text/plain"
echo ""

DIR=$(dirname "$SCRIPT_FILENAME")
LOGFILE="$DIR/test"
JST_DATE=$(TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S')

if [ "$REQUEST_METHOD" = "POST" ]; then
    POST_DATA=$(dd bs=1 count=${CONTENT_LENGTH:-0} 2>/dev/null)
    if [ -n "$POST_DATA" ]; then
        printf '%s\t%s\t%s\n' "$JST_DATE" "POST" "$POST_DATA" >> "$LOGFILE"
        printf 'OK: POST webhook received'
    else
        printf 'No POST data'
    fi
elif [ "$REQUEST_METHOD" = "GET" ]; then
    # QUERY_STRING から hook パラメータを取り出す
    HOOK_VALUE=$(echo "$QUERY_STRING" | sed -n 's/.*hook=\([^&]*\).*/\1/p')
    if [ -n "$HOOK_VALUE" ]; then
        printf '%s\t%s\t%s\n' "$JST_DATE" "GET" "hook=$HOOK_VALUE" >> "$LOGFILE"
        printf 'OK: hook=%s' "$HOOK_VALUE"
    else
        printf 'No hook parameter'
    fi
else
    printf 'Unsupported method: %s' "$REQUEST_METHOD"
fi
