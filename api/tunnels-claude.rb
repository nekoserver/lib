#!/home/box/.rbenv/versions/4.0.7/bin/ruby
# frozen_string_literal: true
# Cloudflare tunnel JSON API with Claude CLI as the default message engine.
# POST /lib/api/tunnels-claude.rb {"message":"Explain these tunnels"}
# Explicit claude_prompt / claude_prmpt and existing engine prefixes also work.
# GET /lib/api/tunnels-claude.rb?ask_id=claude-<uuid> polls an existing job.
# Uses the same HMAC authentication and private CLI worker as tunnels.rb.
require_relative "tunnels_lib"
TunnelsLib.run!(default_format: "json", default_engine: :claude)
