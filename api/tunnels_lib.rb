# frozen_string_literal: true
# Shared Cloudflare tunnel list helper for /lib/api/*.rb CGI
# Allowlisted fields only — never emit tokens / account secrets / origin IPs.
#
# JSON shape:
#   { tunnels: [ { name, id, status, connections: { count, colos }, created_at } ],
#     auth: "oauth"|"api_token", fetched_at: ISO8601 }
#
# Filters (GET query / POST form / POST JSON):
#   status=healthy|down|degraded  (exact, case-insensitive)
#   name=...                      (substring, case-insensitive)
#   format=json|html
#   message=...                   (question to 参謀; enqueue → ask_id)
#   ask_id=...                    (poll for reply)
#   message=codex_prompt=... / message=claude_prompt=...  (explicit LLM; see llm_prompt.rb)
require "json"
require "cgi"
require "open3"
require "time"
require "uri"
require_relative "hmac_auth"
require_relative "ask_sanbo"
require_relative "llm_prompt"

Encoding.default_external = Encoding::UTF_8
Encoding.default_internal = nil

module TunnelsLib
  ACCOUNT_ID = ENV.fetch("CLOUDFLARE_ACCOUNT_ID", "4eb48547c6f6a8194e6c3eb5e700463f")
  CF = "/usr/local/bin/cf"
  OAUTH_LIST = "/usr/local/libexec/cf-tunnels-list"

  module_function

  def html_esc(s)
    CGI.escapeHTML(s.to_s)
  end

  def fetch
    cache = ENV['LIB_TUNNELS_CACHE']
    if cache && File.file?(cache) && Time.now - File.mtime(cache) <= 120
      return [File.read(cache), 'oauth', nil]
    end
    raw, auth, err = fetch_with_token
    return [raw, auth, nil] if raw

    raw, auth, err2 = fetch_with_oauth
    return [raw, auth, nil] if raw

    [nil, "error", err || err2 || "fetch_failed"]
  end

  def fetch_with_token
    token = ENV["CF_CONTAINER_API_TOKEN"].to_s.empty? ? ENV["CLOUDFLARE_API_TOKEN"] : ENV["CF_CONTAINER_API_TOKEN"]
    return [nil, nil, "no_api_token"] if token.nil? || token.empty?

    env = ENV.to_h.merge(
      "CLOUDFLARE_ACCOUNT_ID" => ACCOUNT_ID,
      "CLOUDFLARE_API_TOKEN" => token
    )
    out, status = Open3.capture2e(env, CF, "tunnels", "list")
    bad = !status.success? ||
          out.match?(/403|forbidden|unauthorized|authentication/i) ||
          out.strip.empty? || out.strip == "[]"
    return [nil, nil, out] if bad

    [out, "api_token", nil]
  rescue SystemCallError
    [nil, nil, 'cloudflare_cli_unavailable']
  end

  def fetch_with_oauth
    out, status = Open3.capture2e("sudo", "-n", "-u", "box", OAUTH_LIST)
    return [nil, nil, out] unless status.success?

    [out, "oauth", nil]
  rescue SystemCallError
    [nil, nil, 'cloudflare_oauth_helper_unavailable']
  end

  def redact(err, limit = 400)
    s = (err || "unknown").to_s.gsub(/[A-Za-z0-9_-]{20,}/, "[REDACTED]")
    s[0, limit]
  end

  def sanitize_tunnel(t)
    conns = t.is_a?(Hash) ? (t["connections"] || []) : []
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
      "connections" => { "count" => conns.size, "colos" => colos },
      "created_at" => t["created_at"]
    }
  end

  def parse_raw(raw)
    data = JSON.parse(raw)
    data = [] unless data.is_a?(Array)
    data.select { |t| t.is_a?(Hash) }.map { |t| sanitize_tunnel(t) }
  rescue JSON::ParserError
    :parse_error
  end

  def read_post_body(max = 65_536)
    len = Integer(ENV["CONTENT_LENGTH"] || 0)
    len = 0 if len.negative?
    len = max if len > max
    return "" if len.zero?

    $stdin.read(len).to_s
  rescue ArgumentError
    ""
  end

  # Merge QUERY_STRING + POST. Body wins on conflict.
  # body: raw POST body (already read for HMAC); omit to read stdin (legacy).
  # For application/json, do not use CGI.new — it would consume body.
  def parse_filters(body = nil)
    filters = {}
    URI.decode_www_form(ENV["QUERY_STRING"] || "").each do |k, v|
      filters[k.to_s.downcase] = v.to_s
    end

    return filters unless ENV["REQUEST_METHOD"].to_s.upcase == "POST"

    ct = (ENV["CONTENT_TYPE"] || "").split(";").first.to_s.strip.downcase
    body = read_post_body if body.nil?
    if ct == "application/json" || (ct.empty? && body.lstrip.start_with?("{"))
      begin
        obj = JSON.parse(body)
        obj.each { |k, v| filters[k.to_s.downcase] = v.to_s unless v.nil? } if obj.is_a?(Hash)
      rescue JSON::ParserError
        # ignore
      end
    else
      # application/x-www-form-urlencoded (and similar)
      URI.decode_www_form(body).each do |k, v|
        filters[k.to_s.downcase] = v.to_s
      end
    end
    filters
  end

  def apply_filters(tunnels, filters)
    status_f = filters["status"].to_s.strip.downcase
    name_f = filters["name"].to_s.strip.downcase
    out = tunnels
    out = out.select { |t| t["status"].to_s.downcase == status_f } unless status_f.empty?
    out = out.select { |t| t["name"].to_s.downcase.include?(name_f) } unless name_f.empty?
    out
  end

  # Treat filters["message"] as a question to 参謀 (async).
  # Enqueues ask; returns ask_id + pending until resp exists. Poll with ask_id.
  def attach_message!(payload, filters = nil, default_engine: nil, **fields)
    filters ||= fields
    ask_id = filters["ask_id"].to_s.strip
    unless ask_id.empty?
      looked = LlmPrompt::ID.match?(ask_id) ? LlmPrompt.lookup(ask_id) : AskSanbo.lookup(ask_id)
      payload.merge!(looked)
      return payload
    end

    filters["message"] = LlmPrompt.maybe_percent_decode(filters["message"]) if filters.key?("message")
    routed = LlmPrompt.route(filters, default_engine: default_engine)
    if routed
      engine, prompt = routed
      payload["message"] = AskSanbo.truncate(filters["message"].to_s) unless filters["message"].to_s.empty?
      if engine == :conflict
        payload["ask_error"] = "codex_and_claude_both_given"
        return payload
      end
      reply, err, meta = LlmPrompt.run(engine, prompt, wait_seconds: filters.key?('message') ? 90 : 0)
      payload["via"] = engine
      payload["ask_status"] = meta.fetch('ask_status', err ? 'failed' : 'done')
      payload["ask_id"] = meta['ask_id'] if meta['ask_id']
      payload["reply"] = reply if reply
      payload["ask_error"] = err if err
      if filters.key?('message') && !reply
        payload['reply'] = if err
          "#{engine} の実行に失敗しました（#{err}）。"
        else
          "#{engine} はまだ処理中です。ask_id: #{meta['ask_id']}"
        end
      end
      if meta.is_a?(Hash)
        payload["llm_model"] = meta["model"] if meta["model"].to_s != ""
        payload["llm_effort"] = meta["effort"] if meta["effort"].to_s != ""
      end
      return payload
    end

    msg = filters["message"].to_s
    return payload if msg.empty?

    payload["message"] = AskSanbo.truncate(msg)
    reply, meta = AskSanbo.answer(msg, payload["tunnels"] || [])
    payload["ask_id"] = meta["ask_id"] if meta["ask_id"]
    payload["ask_status"] = meta["ask_status"] if meta["ask_status"]
    payload["via"] = meta["via"] if meta["via"]
    payload["hint"] = meta["hint"] if meta["hint"]
    payload["ask_error"] = meta["ask_error"] if meta["ask_error"]
    payload["reply"] = reply if reply
    payload
  end

  def build_payload(raw, auth, err, filters, default_engine: nil)
    fetched_at = Time.now.utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if raw.nil? || raw.empty?
      return attach_message!({
        "tunnels" => [],
        "auth" => "error",
        "fetched_at" => fetched_at,
        "error" => redact(err)
      }, filters, default_engine: default_engine)
    end

    tunnels = parse_raw(raw)
    if tunnels == :parse_error
      return attach_message!({
        "tunnels" => [],
        "auth" => auth.to_s,
        "fetched_at" => fetched_at,
        "error" => "json_parse_error"
      }, filters, default_engine: default_engine)
    end

    attach_message!({
      "tunnels" => apply_filters(tunnels, filters),
      "auth" => auth.to_s,
      "fetched_at" => fetched_at
    }, filters, default_engine: default_engine)
  end

  def render_html(payload)
    auth = html_esc(payload["auth"])
    fetched = html_esc(payload["fetched_at"])
    tunnels = payload["tunnels"] || []
    lines = []
    lines << %(<div class="cf-tunnels-api" data-auth="#{auth}" data-count="#{tunnels.size}" data-fetched-at="#{fetched}">)
    lines << %(<p class="cf-tunnels-meta">tunnels: #{tunnels.size} (auth=#{auth}; fetched_at=#{fetched})</p>)
    if payload["message"]
      lines << %(<p class="cf-tunnels-message">Q: #{html_esc(payload["message"])}</p>)
    end
    if payload["reply"]
      lines << %(<p class="cf-tunnels-reply">A: #{html_esc(payload["reply"])}</p>)
    end
    if payload["ask_error"]
      lines << %(<p class="cf-tunnels-ask-error">ask_error: #{html_esc(payload["ask_error"])}</p>)
    end
    if payload["error"]
      lines << %(<p class="cf-tunnels-error">#{html_esc(payload["error"])}</p>)
    end
    if tunnels.empty?
      lines << %(<p class="cf-tunnels-empty">(no tunnels)</p>)
    else
      lines << %(<table class="cf-tunnels-table">)
      lines << "<thead><tr><th>name</th><th>status</th><th>id</th><th>connections</th><th>created_at</th></tr></thead>"
      lines << "<tbody>"
      tunnels.each do |t|
        name = html_esc(t["name"])
        status = html_esc(t["status"])
        tid = html_esc(t["id"])
        created = html_esc(t["created_at"])
        conn = t["connections"] || {}
        n = conn["count"].to_i
        colos = Array(conn["colos"]).map { |c| html_esc(c) }.join(", ")
        conn_s = colos.empty? ? n.to_s : "#{n} (#{colos})"
        lines << "<tr><td>#{name}</td><td>#{status}</td><td><code>#{tid}</code></td><td>#{conn_s}</td><td>#{created}</td></tr>"
      end
      lines << "</tbody></table>"
    end
    lines << "</div>"
    lines.join("\n") + "\n"
  end

  def respond!(payload, format)
    ctype = format == "html" ? "text/html" : "application/json"
    print "Content-Type: #{ctype}; charset=utf-8\r\n"
    print "Cache-Control: no-store\r\n"
    print "X-LLM-Engine: #{payload["via"]}\r\n" if payload["via"].to_s != ""
    print "X-LLM-Model: #{payload["llm_model"]}\r\n" if payload["llm_model"].to_s != ""
    print "X-LLM-Effort: #{payload["llm_effort"]}\r\n" if payload["llm_effort"].to_s != ""
    print "\r\n"
    if format == "html"
      print render_html(payload)
    else
      print JSON.pretty_generate(payload)
      print "\n"
    end
  end

  # force_format: "json" | "html" | nil
  # Auth: valid HMAC → allow; else allowlisted REMOTE_ADDR → allow; else 401.
  def run!(default_format: "json", force_format: nil, default_engine: nil)
    method = ENV["REQUEST_METHOD"].to_s.upcase
    if ENV.fetch('CONTENT_LENGTH', '0').to_i > 65_536
      print "Status: 413 Payload Too Large\r\nContent-Type: application/json\r\n\r\n{\"error\":\"body_too_large\"}\n"
      return
    end
    body = method == "POST" ? read_post_body : ""
    filters = parse_filters(body)
    require_relative 'railway_exec'
    railway_command = RailwayExec.route(filters)
    uptime_command = filters['command'].to_s == 'railway_uptime' || filters['message'].to_s == 'railway_uptime'
    protected_request = uptime_command || LlmPrompt.route(filters, default_engine: default_engine) || !filters['message'].to_s.empty? || !filters['ask_id'].to_s.empty?
    return unless HmacAuth.enforce!(body, require_hmac: !!protected_request)
    unless railway_command.nil?
      unless %w[GET POST].include?(method)
        print "Status: 405 Method Not Allowed\r\nAllow: GET, POST\r\nContent-Type: application/json\r\n\r\n{\"error\":\"unsupported_method\"}\n"
        return
      end
      respond!(RailwayExec.run(railway_command), force_format || 'json')
      return
    end
    if uptime_command
      unless %w[GET POST].include?(method)
        print "Status: 405 Method Not Allowed\r\nAllow: GET, POST\r\nContent-Type: application/json\r\n\r\n{\"error\":\"unsupported_method\"}\n"
        return
      end
      seconds = Float(File.read('/proc/uptime').split.first).floor
      boot = Integer(File.read('/proc/stat').match(/^btime (\d+)$/)[1])
      days, rest = seconds.divmod(86_400)
      hours, rest = rest.divmod(3_600)
      minutes = rest / 60
      reply = "Railway VMのOS稼働時間: #{days}日#{hours}時間#{minutes}分（課金対象時間ではありません）"
      respond!({
        'command' => 'railway_uptime',
        'uptime_seconds' => seconds,
        'booted_at' => Time.at(boot).utc.iso8601,
        'checked_at' => Time.now.utc.iso8601,
        'source' => '/proc/uptime',
        'billing_time' => false,
        'reply' => reply
      }, force_format || 'json')
      return
    end
    if LlmPrompt.route(filters, default_engine: default_engine) && method != 'POST'
      error = default_engine ? "use_post_for_#{default_engine}" : "use_post_for_codex"
      print "Status: 405 Method Not Allowed\r\nAllow: POST\r\nContent-Type: application/json\r\n\r\n{\"error\":\"#{error}\"}\n"
      return
    end
    fmt = (force_format || filters["format"] || default_format).to_s.downcase
    fmt = default_format unless %w[json html].include?(fmt)

    # Poll-only: ask_id without new message — do not refetch tunnels
    if !filters["ask_id"].to_s.strip.empty? && filters["message"].to_s.empty?
      id = filters['ask_id']
      payload = LlmPrompt::ID.match?(id) ? LlmPrompt.lookup(id) : AskSanbo.lookup(id)
      respond!(payload, fmt)
      return
    end

    raw, auth, err = fetch
    payload = build_payload(raw, auth, err, filters, default_engine: default_engine)
    respond!(payload, fmt)
  end
end
