# frozen_string_literal: true
# Stream capability metadata kept outside the tunnels list / askgk controller.
require "json"
require "uri"

module ConversationStream
  EMBED_PATH = "/lib/conversation-embed.html"
  STREAM_PATH = "/lib/api/chat"
  PROTOCOLS = %w[websocket sse ndjson jsonseq].freeze
  HOST_SUFFIXES = %w[nekomaneki.work nekoflare.workers.dev].freeze
  HOSTS_HEADER = "HTTP_X_LIB_STREAM_HOSTS"
  OBSERVER_SOCKET = "/run/lib-chat-observer/observer.sock"

  module_function

  def metadata(env = ENV)
    {
      "embed_path" => EMBED_PATH,
      "stream_path" => STREAM_PATH,
      "protocols" => PROTOCOLS,
      "authentication" => "conversation-session",
      "observer_configured" => !env["LIB_CHAT_APP_SOCKET"].to_s.empty? && !env["LIB_CHAT_THREAD_ID"].to_s.empty?,
      "observer_socket_present" => File.socket?(OBSERVER_SOCKET),
      "hosts" => registered_hosts(env[HOSTS_HEADER])
    }
  rescue SystemCallError
    {
      "embed_path" => EMBED_PATH,
      "stream_path" => STREAM_PATH,
      "protocols" => PROTOCOLS,
      "authentication" => "conversation-session",
      "observer_configured" => false,
      "observer_socket_present" => false,
      "hosts" => []
    }
  end

  def registered_hosts(raw)
    records = JSON.parse(raw.to_s.empty? ? "[]" : raw.to_s)
    return [] unless records.is_a?(Array)

    records.filter_map do |record|
      begin
        next unless record.is_a?(Hash)
        id = record["id"].to_s
        label = record["label"].to_s
        uri = URI.parse(record["origin"].to_s)
        hostname = uri.host.to_s.downcase
        next unless id.match?(/\A[a-z0-9][a-z0-9_-]{0,31}\z/i) && label.length.between?(1, 64)
        next unless uri.scheme == "https" && uri.userinfo.nil? && uri.query.nil? && uri.fragment.nil?
        next unless uri.path.to_s.empty? && (uri.port.nil? || uri.port == 443)
        next unless HOST_SUFFIXES.any? { |suffix| hostname == suffix || hostname.end_with?(".#{suffix}") }

        priority = Integer(record["priority"])
        next unless priority.between?(0, 10_000)
        { "id" => id, "label" => label, "origin" => "https://#{hostname}",
          "priority" => priority, "enabled" => record["enabled"] == true }
      rescue URI::InvalidURIError, ArgumentError, TypeError
        nil
      end
    end.first(100)
  rescue JSON::ParserError
    []
  end
end
