# frozen_string_literal: true
require 'minitest/autorun'
require 'stringio'
require 'tmpdir'
require 'socket'
require_relative '../api/tunnels.claude'

class TunnelsClaudeRbTest < Minitest::Test
  Status = Struct.new(:ok) { def success? = ok }

  # cf 1.0.0-beta.31 (checked 2026-11-14): `--json` is "Unknown argument: json", and the plain
  # output is a `result_info: {...}` line followed by the JSON array.
  CF_OUTPUT = "result_info: {\"page\":1,\"per_page\":1000,\"count\":1,\"total_count\":1}\n" \
              "[\n  {\n    \"id\": \"x\",\n    \"name\": \"nekoroot\",\n    \"status\": \"healthy\"\n  }\n]\n"

  def with_cf_output(out, ok = true)
    calls = []
    env = ENV.to_h
    ENV['CF_CONTAINER_API_TOKEN'] = 'test-token'
    capture = Open3.method(:capture2e)
    Open3.define_singleton_method(:capture2e) { |*args| calls << args; [out, Status.new(ok)] }
    [TunnelsLib.fetch_with_token, calls]
  ensure
    Open3.define_singleton_method(:capture2e, capture)
    ENV.replace(env)
  end

  def test_token_fetch_reads_the_json_array_after_result_info
    (raw, auth, err), calls = with_cf_output(CF_OUTPUT)
    assert_nil err
    assert_equal 'api_token', auth
    assert_equal [TunnelsLib::CF, 'tunnels', 'list'], calls.first.drop(1)
    assert_equal [{ 'name' => 'nekoroot', 'id' => 'x', 'status' => 'healthy', 'connections' => { 'count' => 0, 'colos' => [] } }],
                 TunnelsLib.parse_raw(raw).map { |t| t.slice('name', 'id', 'status', 'connections') }
  end

  def test_token_fetch_rejects_an_empty_listing_after_result_info
    (raw, _auth, err), = with_cf_output("result_info: {\"count\":0}\n[]\n")
    assert_nil raw
    assert_includes err, '[]'
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

  # Runs the CGI with a signed POST against a fake worker socket and a cached tunnel list.
  def submitted_job(message)
    Dir.mktmpdir do |dir|
      cache = File.join(dir, 'tunnels.json')
      File.write(cache, JSON.generate([{ 'name' => 'nekoroot', 'id' => 'x', 'status' => 'healthy', 'connections' => 3,
                                         'credentials_file' => 'secret-path' }]))
      sock = File.join(dir, 'worker.sock')
      server = UNIXServer.new(sock)
      seen = Thread.new do
        client = server.accept
        job = JSON.parse(client.gets)
        client.puts(JSON.generate('ask_status' => 'done', 'ask_id' => "#{job['engine']}-00000000-0000-0000-0000-000000000000", 'reply' => 'ok'))
        client.close
        job
      end
      body = JSON.generate('message' => message)
      ts = Time.now.to_i.to_s
      path = '/lib/api/tunnels'
      env = { 'REQUEST_METHOD' => 'POST', 'REQUEST_URI' => path, 'SCRIPT_NAME' => path,
              'CONTENT_TYPE' => 'application/json', 'CONTENT_LENGTH' => body.bytesize.to_s,
              'HTTP_X_TIMESTAMP' => ts, 'HTTP_X_SIGNATURE' => HmacAuth.sign('test-secret', 'POST', path, ts, body),
              'ORIGIN_HMAC_SECRET' => 'test-secret', 'REMOTE_ADDR' => '203.0.113.9',
              'LIB_CODEX_SOCKET' => sock, 'LIB_TUNNELS_CACHE' => cache }
      out, err, = Open3.capture3(env, RbConfig.ruby, File.expand_path('../api/tunnels.claude.rb', __dir__), stdin_data: body)
      assert_includes out, %q("reply": "ok"), err
      seen.value
    ensure
      server&.close
    end
  end

  def test_a_message_without_an_engine_prefix_goes_to_claude
    assert_equal 'claude', submitted_job('トンネルの状態を教えて')['engine']
    assert_equal 'codex', submitted_job('codex_prompt="hello"')['engine']
  end

  # The sandbox has no Cloudflare credentials, so Claude gets the list the API already fetched.
  def test_claude_prompt_carries_the_sanitized_tunnel_list
    prompt = submitted_job('トンネルの状態を教えて')['prompt']
    assert_includes prompt, '"name":"nekoroot"'
    assert_includes prompt, '"count":3'
    refute_includes prompt, 'secret-path'
    assert prompt.end_with?("トンネルの状態を教えて"), prompt
    assert_equal 'hello', submitted_job('codex_prompt=hello')['prompt']
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
