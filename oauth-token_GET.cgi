#!/bin/bash
echo "Content-Type: text/plain"
echo ""
PARAM="${QUERY_STRING}"
if [ -n "$PARAM" ]; then
    DIR=$(dirname "$SCRIPT_FILENAME")
    printf '%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PARAM" >> "$DIR/oauth-token.dat"
    printf 'OK: %s' "$PARAM"
else
    printf 'No parameter'
fi
