# frozen_string_literal: true
require 'json'
require 'socket'
require 'timeout'
require 'uri'

module LlmPrompt
  SOCKET = ENV.fetch('LIB_CODEX_SOCKET', '/run/lib-codex/worker.sock')
  MAX_PROMPT = 16_384
  ID = /\A(?:codex|claude)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\z/
  module_function

  def maybe_percent_decode(value)
    # Query and form values have already been decoded by parse_filters.
    value.to_s
  end

  def route(filters)
    prompts = {}
    %w[codex claude].each do |engine|
      key = "#{engine}_prompt"
      prompts[engine.to_sym] = filters[key].to_s if filters.key?(key)
    end
    match = filters['message'].to_s.match(/\A(codex|claude)_prompt=(.*)\z/m)
    if match
      value = match[2]
      if value.length >= 2 && [['"', '"'], ['“', '”']].any? { |left, right| value.start_with?(left) && value.end_with?(right) }
        value = URI.decode_www_form_component(value[1...-1])
      end
      prompts[match[1].to_sym] = value
    end
    return nil if prompts.empty?
    return [:conflict, nil] if prompts.size > 1
    prompts.first
  end

  def request(payload)
    Timeout.timeout(5) do
      UNIXSocket.open(SOCKET) do |socket|
        socket.puts(JSON.generate(payload))
        line = socket.gets(65_537)
        raise IOError, 'Invalid worker response' if line.nil? || line.bytesize > 65_536
        JSON.parse(line)
      end
    end
  rescue SystemCallError, IOError, Timeout::Error, JSON::ParserError
    { 'ask_error' => 'codex_worker_unavailable', 'ask_status' => 'failed', 'via' => 'codex' }
  end

  def run(engine, prompt, wait_seconds: 0)
    return [nil, 'unsupported_engine', { 'ask_status' => 'failed' }] unless %i[codex claude].include?(engine)
    return [nil, 'empty_prompt', { 'ask_status' => 'failed' }] if prompt.to_s.strip.empty?
    return [nil, 'prompt_too_large', { 'ask_status' => 'failed' }] if prompt.bytesize > MAX_PROMPT
    result = request('op' => 'submit', 'engine' => engine.to_s, 'prompt' => prompt)
    deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + wait_seconds
    while %w[pending running].include?(result['ask_status']) && ID.match?(result['ask_id'].to_s)
      remaining = deadline - Process.clock_gettime(Process::CLOCK_MONOTONIC)
      break if remaining <= 0
      sleep [0.5, remaining].min
      result = lookup(result['ask_id'])
    end
    [result.delete('reply'), result.delete('ask_error'), result]
  end

  def lookup(id)
    return { 'ask_error' => 'invalid_ask_id' } unless ID.match?(id.to_s)
    request('op' => 'poll', 'ask_id' => id)
  end
end
