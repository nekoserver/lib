# frozen_string_literal: true
require "json"
require "securerandom"
require "shellwords"
require "open3"
require "net/http"
require "uri"

module AskSanbo
  ASK_DIR = "/var/www/html/lib/api/ask"
  HW_FILE = File.join(ASK_DIR, "box-hw.txt")
  WEBHOOK_FILE = "/etc/apache2/secrets/lib-api-ask-webhook"
  MAX_MSG = 4096
  MAX_OUT = 16_384
  WAIT_SEC = 50
  POLL = 0.4

  ALLOWED = %w[
    uptime uname hostname date whoami id pwd df free nproc lscpu lsblk
    cat head tail wc ls ps ip ss ping curl ruby python3
    systemctl journalctl apache2ctl cloudflared cf
  ].freeze

  module_function

  def truncate(msg)
    msg = msg.to_s
    msg.bytesize > MAX_MSG ? msg.byteslice(0, MAX_MSG) : msg
  end

  def write_json(path, obj)
    File.write(path, JSON.pretty_generate(obj) + "\n")
  end

  def read_req(id)
    path = File.join(ASK_DIR, "req-#{id}.json")
    return nil unless File.file?(path)
    JSON.parse(File.read(path))
  rescue JSON::ParserError
    nil
  end

  def read_reply(id)
    path = File.join(ASK_DIR, "resp-#{id}.json")
    return nil unless File.file?(path)
    obj = JSON.parse(File.read(path))
    obj.is_a?(Hash) ? obj["reply"].to_s : nil
  rescue JSON::ParserError
    nil
  end

  def lookup(ask_id)
    id = ask_id.to_s.strip
    return { "ask_error" => "missing_ask_id" } if id.empty?
    req = read_req(id)
    return { "ask_id" => id, "ask_error" => "unknown_ask_id" } if req.nil?
    reply = read_reply(id)
    out = {
      "ask_id" => id,
      "message" => req["message"],
      "ask_status" => reply && !reply.empty? ? "done" : "pending"
    }
    out["reply"] = reply if reply && !reply.empty?
    out
  end

  def hw_summary
    return File.read(HW_FILE).to_s.strip if File.file?(HW_FILE)
    "ハードウェア情報ファイルがありません。"
  rescue StandardError
    "ハードウェア情報を読めませんでした。"
  end

  def tunnel_summary(tunnels)
    return "取得できたトンネルはありません。" if tunnels.nil? || tunnels.empty?
    tunnels.map do |t|
      next unless t.is_a?(Hash)
      n = (t.dig("connections", "count") || 0).to_i
      "#{t["name"]}: #{t["status"]}（接続#{n}）"
    end.compact.join(" / ")
  end

  def webhook_url
    env = ENV["LIB_API_ASK_WEBHOOK"].to_s.strip
    return env unless env.empty?
    File.read(WEBHOOK_FILE).to_s.strip
  rescue Errno::ENOENT
    ""
  end

  def webhook_configured?
    !webhook_url.empty?
  end

  def fire_webhook!(id)
    url = webhook_url
    return :no_webhook if url.empty?
    uri = URI.parse(url)
    http = Net::HTTP.new(uri.host, uri.port)
    http.use_ssl = (uri.scheme == "https")
    http.open_timeout = 5
    http.read_timeout = 15
    req = Net::HTTP::Post.new(uri)
    req["Content-Type"] = "application/json"
    req.body = JSON.generate("id" => id, "source" => "lib-api")
    res = http.request(req)
    res.code.to_i.between?(200, 299) ? :ok : :"http_#{res.code}"
  rescue StandardError => e
    :"err_#{e.class}"
  end

  def wait_reply(id)
    deadline = Time.now + WAIT_SEC
    while Time.now < deadline
      r = read_reply(id)
      return r if r && !r.empty?
      sleep POLL
    end
    nil
  end

  def command_allowed?(q)
    return false if q.nil? || q.strip.empty?
    return false if q.match?(/[|;&`$<>(){}]|>>|&&|\|\|/)
    tokens = Shellwords.shellsplit(q)
    return false if tokens.empty?
    ALLOWED.include?(File.basename(tokens[0]))
  rescue ArgumentError
    false
  end

  def run_allowed_command(q)
    return "拒否: 許可リスト外、または危険な文字を含みます。" unless command_allowed?(q)
    tokens = Shellwords.shellsplit(q)
    if File.basename(tokens[0]) == "cf"
      tokens[0] = "/usr/local/bin/cf"
      # tunnels list as www-data: use oauth helper (same as tunnels API)
      if tokens[1..] == ["tunnels", "list"]
        out, status = Open3.capture2e("sudo", "-n", "-u", "box", "/usr/local/libexec/cf-tunnels-list")
        out = out.to_s.dup.force_encoding("BINARY").encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
        out = out.gsub(/\e\[[0-9;]*[A-Za-z]/, "")
        out = out.byteslice(0, MAX_OUT) + "
...(truncated)" if out.bytesize > MAX_OUT
        return out.empty? ? "(exit #{status.exitstatus}, no output)" : out.rstrip
      end
    end
    env = ENV.to_h.merge("LANG" => "C.UTF-8", "LC_ALL" => "C.UTF-8", "PATH" => "/usr/local/bin:/usr/bin:/bin", "NO_COLOR" => "1", "FORCE_COLOR" => "0")
    out, status = Open3.capture2e(env, *tokens)
    out = out.to_s.dup.force_encoding("BINARY").encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
    out = out.gsub(/\e\[[0-9;]*[A-Za-z]/, "")
    out = out.byteslice(0, MAX_OUT) + "\n...(truncated)" if out.bytesize > MAX_OUT
    out.empty? ? "(exit #{status.exitstatus}, no output)" : out.rstrip
  rescue StandardError => e
    "実行エラー: #{e.class}"
  end

  def local_reply(msg, tunnels)
    q = msg.to_s.strip
    tunnels = tunnels.is_a?(Array) ? tunnels : []
    by_name = {}
    tunnels.each { |t| by_name[t["name"].to_s.downcase] = t if t.is_a?(Hash) }
    tun = tunnel_summary(tunnels)

    return run_allowed_command(q) if command_allowed?(q)

    if q.match?(/ハードウェア|hardware|CPU|メモリ|memory|構成|スペック|マシン/i)
      return "このオリジン（私の作業マシン）の構成です。\n#{hw_summary}\n（トンネル: #{tun}）"
    end

    mentioned = by_name.keys.select { |n| !n.empty? && q.downcase.include?(n) }
    if mentioned.any?
      parts = mentioned.map do |n|
        t = by_name[n]
        st = t["status"].to_s
        alive = st == "healthy" ? "生きてます（healthy）" : "healthyではありません（#{st}）"
        "#{t["name"]} は#{alive}。"
      end
      extra = q.match?(/neko(?!root)/i) && !by_name.key?("neko") ? " 一覧に neko は出ていません。" : ""
      return parts.join(" ") + extra + " 全体: #{tun}"
    end

    if q.match?(/neko(?!root)/i) && !by_name.key?("neko")
      return "neko は一覧にありません（down か未登録）。いま見えるのは → #{tun}"
    end

    if q.match?(/トンネル|tunnel|状態|ステータス|状況|healthy|down/i)
      return tun
    end

    nil # needs 参謀
  end

  def answer(message, tunnels)
    msg = truncate(message)
    return [nil, { "ask_error" => "empty_message" }] if msg.empty?

    Dir.mkdir(ASK_DIR) unless Dir.exist?(ASK_DIR)
    id = SecureRandom.uuid
    write_json(File.join(ASK_DIR, "req-#{id}.json"), {
      "id" => id,
      "message" => msg,
      "tunnels" => tunnels,
      "created_at" => Time.now.utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    })

    # Fast path: allowlisted commands / local knowledge
    local = local_reply(msg, tunnels)
    if local
      write_json(File.join(ASK_DIR, "resp-#{id}.json"), { "id" => id, "reply" => local, "via" => "local" })
      return [local, { "ask_id" => id, "ask_status" => "done", "via" => "local" }]
    end

    # 参謀 path: webhook wake + wait
    unless webhook_configured?
      reply = "参謀起こし用 webhook 未設定。許可コマンド／トンネル／ハード以外はチャットへ。"
      write_json(File.join(ASK_DIR, "resp-#{id}.json"), { "id" => id, "reply" => reply, "via" => "unset" })
      return [reply, { "ask_id" => id, "ask_status" => "done", "via" => "unset",
                       "hint" => "Set LIB_API_ASK_WEBHOOK or /etc/apache2/secrets/lib-api-ask-webhook" }]
    end

    st = fire_webhook!(id)
    reply = wait_reply(id)
    if reply && !reply.empty?
      [reply, { "ask_id" => id, "ask_status" => "done", "via" => "sanbo", "webhook" => st.to_s }]
    else
      fallback = "参謀タイムアウト（webhook=#{st}）。ask_id=#{id}"
      write_json(File.join(ASK_DIR, "resp-#{id}.json"), { "id" => id, "reply" => fallback, "via" => "timeout" })
      [fallback, { "ask_id" => id, "ask_status" => "done", "via" => "timeout", "webhook" => st.to_s }]
    end
  end
end
