#!/bin/bash
echo "Content-Type: text/plain"
echo ""
POST_DATA=$(dd bs=1 count=${CONTENT_LENGTH:-0} 2>/dev/null)
if [ -n "$POST_DATA" ]; then
    DIR=$(dirname "$SCRIPT_FILENAME")
    printf '%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$POST_DATA" >> "$DIR/oauth-token.dat"
    printf 'OK: %s' "$POST_DATA"
else
    printf 'No POST data'
fi
