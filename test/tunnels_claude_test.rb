# frozen_string_literal: true
require 'minitest/autorun'
require 'stringio'
require_relative '../api/tunnels_lib'

class TunnelsClaudeTest < Minitest::Test
  ID = 'claude-12345678-1234-1234-1234-123456789abc'

  def setup
    @env, @input, @output = ENV.to_h, $stdin, $stdout
    @secret = HmacAuth.instance_variable_get(:@secret)
    HmacAuth.instance_variable_set(:@secret, 'test-key')
    %w[HTTP_X_TIMESTAMP HTTP_X_SIGNATURE HTTP_CF_CONNECTING_IP CF_ACCESS REDIRECT_CF_ACCESS].each { |key| ENV.delete(key) }
    ENV['REMOTE_ADDR'] = '127.0.0.1'
    @calls = []
  end

  def teardown
    ENV.replace(@env)
    $stdin, $stdout = @input, @output
    HmacAuth.instance_variable_set(:@secret, @secret)
  end

  def invoke(body = '', method: 'POST', query: '', signed: true, content_type: 'application/json')
    ENV['REQUEST_METHOD'], ENV['QUERY_STRING'], ENV['CONTENT_TYPE'] = method, query, content_type
    ENV['REQUEST_URI'] = '/lib/api/tunnels-claude.rb' + (query.empty? ? '' : '?' + query)
    ENV['CONTENT_LENGTH'] = body.bytesize.to_s
    if signed
      ENV['HTTP_X_TIMESTAMP'] = Time.now.to_i.to_s
      ENV['HTTP_X_SIGNATURE'] = HmacAuth.sign('test-key', method, ENV['REQUEST_URI'], ENV['HTTP_X_TIMESTAMP'], body)
    end
    $stdin, $stdout = StringIO.new(body), StringIO.new
    calls = @calls
    worker = lambda do |payload|
      calls << payload
      { 'ask_id' => ID, 'ask_status' => 'done', 'via' => 'claude', 'reply' => 'Claude reply' }
    end
    fetch, request = TunnelsLib.method(:fetch), LlmPrompt.method(:request)
    TunnelsLib.define_singleton_method(:fetch) { ['[]', 'oauth', nil] }
    LlmPrompt.define_singleton_method(:request, worker)
    load File.expand_path('../api/tunnels-claude.rb', __dir__)
    $stdout.string
  ensure
    TunnelsLib.define_singleton_method(:fetch, fetch) if fetch
    LlmPrompt.define_singleton_method(:request, request) if request
  end

  def test_signed_json_submits_literal_message_to_claude
    message = '日本語 + %20 $(id)'
    result = invoke(JSON.generate('message' => message))
    assert_equal [{ 'op' => 'submit', 'engine' => 'claude', 'prompt' => message }], @calls
    assert_equal 'Claude reply', JSON.parse(result.split("\r\n\r\n", 2).last)['reply']
    assert_includes result, 'X-LLM-Engine: claude'
  end

  def test_form_and_slash_command_default_to_claude
    invoke('message=%2Fusage', content_type: 'application/x-www-form-urlencoded')
    assert_equal 'claude', @calls.first['engine']
    assert_equal '/usage', @calls.first['prompt']
  end

  def test_signed_poll_does_not_submit_again
    invoke(method: 'GET', query: "ask_id=#{ID}")
    assert_equal [{ 'op' => 'poll', 'ask_id' => ID }], @calls
  end

  def test_unsigned_loopback_cannot_execute
    assert_includes invoke('{"message":"hello"}', signed: false), '401 Unauthorized'
    assert_empty @calls
  end

  def test_get_message_requires_post
    assert_includes invoke(method: 'GET', query: 'message=hello'), '405 Method Not Allowed'
    assert_empty @calls
  end

  def test_original_routes_and_explicit_engine_selection_are_preserved
    assert_nil LlmPrompt.route('message' => 'hello')
    assert_equal [:codex, '/usage'], LlmPrompt.route('message' => '/usage')
    assert_equal [:claude, 'hello'], LlmPrompt.route({ 'claude_prmpt' => 'hello' }, default_engine: :claude)
    assert_equal [:codex, 'hello'], LlmPrompt.route({ 'codex_prompt' => 'hello' }, default_engine: :claude)
    assert_equal [:conflict, nil], LlmPrompt.route({ 'codex_prompt' => 'a', 'claude_prompt' => 'b' }, default_engine: :claude)
  end
end
