#!/usr/bin/env ruby
# frozen_string_literal: true
# Claude Code sandbox variant of tunnels.rb (same API / auth / filters).
#
# Differences from tunnels.rb (original left untouched for the box host):
#   - shebang uses PATH ruby (no /home/box/.rbenv here)
#   - `cf tunnels list --json` (plain output is a table, not JSON)
#   - connections may be an Integer count instead of an Array
#   - a message waits up to 300 s for the LLM reply (original: 90 s);
#     the web server's CGI timeout must exceed this
require_relative "../../api/tunnels_lib"

module LlmPrompt
  WAIT_SECONDS = 300 unless const_defined?(:WAIT_SECONDS, false)

  # Alias once: loading this file again must not wrap the override in itself.
  singleton_class.alias_method :run_with_caller_wait, :run unless respond_to?(:run_with_caller_wait)

  # attach_message! waits only when a message was given; keep 0 (submit-and-poll) as is.
  def self.run(engine, prompt, wait_seconds: 0)
    run_with_caller_wait(engine, prompt, wait_seconds: wait_seconds.positive? ? WAIT_SECONDS : 0)
  end
end

module TunnelsLib
  module_function

  def fetch_with_token
    token = ENV["CF_CONTAINER_API_TOKEN"].to_s.empty? ? ENV["CLOUDFLARE_API_TOKEN"] : ENV["CF_CONTAINER_API_TOKEN"]
    return [nil, nil, "no_api_token"] if token.nil? || token.empty?

    env = ENV.to_h.merge(
      "CLOUDFLARE_ACCOUNT_ID" => ACCOUNT_ID,
      "CLOUDFLARE_API_TOKEN" => token
    )
    out, status = Open3.capture2e(env, CF, "tunnels", "list", "--json")
    bad = !status.success? ||
          out.match?(/403|forbidden|unauthorized|authentication/i) ||
          out.strip.empty? || out.strip == "[]"
    return [nil, nil, out] if bad

    [out, "api_token", nil]
  rescue SystemCallError
    [nil, nil, 'cloudflare_cli_unavailable']
  end

  def sanitize_tunnel(t)
    conns = t.is_a?(Hash) ? (t["connections"] || []) : []
    count = conns.is_a?(Integer) ? conns : nil
    conns = [] unless conns.is_a?(Array)
    colos = []
    conns.each do |c|
      next unless c.is_a?(Hash) && c["colo_name"]
      colos << c["colo_name"].to_s
    end
    {
      "name" => (t["name"] || "").to_s,
      "id" => (t["id"] || "").to_s,
      "status" => (t["status"] || "").to_s,
      "connections" => { "count" => count || conns.size, "colos" => colos },
      "created_at" => t["created_at"]
    }
  end
end

# Run only as the CGI script, so tests can load the overrides.
TunnelsLib.run!(default_format: "json") if File.expand_path($PROGRAM_NAME) == File.expand_path(__FILE__)
