# frozen_string_literal: true
require 'minitest/autorun'
require 'stringio'
require_relative '../api/tunnels.claude'

class TunnelsClaudeRbTest < Minitest::Test
  Status = Struct.new(:ok) { def success? = ok }

  def test_token_fetch_requests_json_from_cf
    calls = []
    env = ENV.to_h
    ENV['CF_CONTAINER_API_TOKEN'] = 'test-token'
    capture = Open3.method(:capture2e)
    Open3.define_singleton_method(:capture2e) { |*args| calls << args; ['[{"name":"a"}]', Status.new(true)] }
    raw, auth, = TunnelsLib.fetch_with_token
    assert_equal '[{"name":"a"}]', raw
    assert_equal 'api_token', auth
    assert_equal [TunnelsLib::CF, 'tunnels', 'list', '--json'], calls.first.drop(1)
  ensure
    Open3.define_singleton_method(:capture2e, capture)
    ENV.replace(env)
  end

  def test_connections_given_as_a_count_are_kept
    tunnel = TunnelsLib.sanitize_tunnel({ 'name' => 'nekoroot', 'id' => 'x', 'status' => 'healthy', 'connections' => 3 })
    assert_equal({ 'count' => 3, 'colos' => [] }, tunnel['connections'])
    listed = TunnelsLib.sanitize_tunnel({ 'connections' => [{ 'colo_name' => 'nrt01' }, { 'colo_name' => 'kix01' }] })
    assert_equal({ 'count' => 2, 'colos' => %w[nrt01 kix01] }, listed['connections'])
  end

  def test_message_waits_up_to_300_seconds_and_submit_only_stays_zero
    seen = []
    original = LlmPrompt.method(:run_with_caller_wait)
    LlmPrompt.define_singleton_method(:run_with_caller_wait) { |_engine, _prompt, wait_seconds: 0| seen << wait_seconds; ['ok', nil, {}] }
    TunnelsLib.attach_message!({ 'tunnels' => [] }, { 'message' => 'claude_prompt="hello"' })
    TunnelsLib.attach_message!({ 'tunnels' => [] }, { 'claude_prompt' => 'hello' })
    assert_equal [300, 0], seen
  ensure
    LlmPrompt.define_singleton_method(:run_with_caller_wait, original)
  end

  def test_loading_does_not_run_the_cgi
    out = $stdout
    $stdout = StringIO.new
    load File.expand_path('../api/tunnels.claude.rb', __dir__)
    assert_equal '', $stdout.string
    # A second load must keep the 300 s override working (no self-wrapping).
    seen = []
    request = LlmPrompt.method(:request)
    LlmPrompt.define_singleton_method(:request) { |_payload| seen << :called; { 'ask_status' => 'done', 'reply' => 'ok' } }
    assert_equal 'ok', LlmPrompt.run(:claude, 'hello', wait_seconds: 90).first
    assert_equal [:called], seen
  ensure
    LlmPrompt.define_singleton_method(:request, request) if request
    $stdout = out
  end
end
