#!/home/box/.rbenv/versions/4.0.7/bin/ruby
# frozen_string_literal: true
# Cloudflare tunnel status JSON API (Ruby CGI)
#
# GET  /lib/api/tunnels.rb
# POST /lib/api/tunnels.rb
#   Content-Type: application/json  OR  application/x-www-form-urlencoded
#
# Response: application/json
#   { "tunnels": [...], "auth": "oauth"|"api_token", "fetched_at": "..." }
#
# Optional filters: status=healthy|down|degraded, name=..., format=json|html; message echoed on 200
#
# Secrets never printed. Data via API token or sudo OAuth list helper.
# Auth: X-Timestamp + X-Signature HMAC (see CALLER_SPEC.md), or IP allowlist.
# Existing /lib/tunnels.cgi HTML UI is unchanged.
require_relative "tunnels_lib"
TunnelsLib.run!(default_format: "json")
