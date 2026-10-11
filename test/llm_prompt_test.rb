# frozen_string_literal: true
require 'minitest/autorun'
require 'stringio'
require_relative '../api/llm_prompt'
require_relative '../api/hmac_auth'

class LlmPromptTest < Minitest::Test
  def test_routes_both_supported_engines_without_shell_parsing
    prompt = 'echo $(id); a+b%20 & <tag>'
    assert_equal [:codex, prompt], LlmPrompt.route('codex_prompt' => prompt)
    assert_equal [:claude, prompt], LlmPrompt.route('message' => "claude_prompt=#{prompt}")
    assert_nil LlmPrompt.route('message' => 'ordinary question')
  end

  def test_conflicting_engines_and_invalid_job_ids
    assert_equal [:conflict, nil], LlmPrompt.route('codex_prompt' => 'a', 'claude_prompt' => 'b')
    assert_equal 'invalid_ask_id', LlmPrompt.lookup('../auth.json')['ask_error']
    assert_equal 'invalid_ask_id', LlmPrompt.lookup('codex-../../auth.json')['ask_error']
  end

  def test_size_limit_does_not_truncate_or_submit
    _, error, = LlmPrompt.run(:codex, 'あ' * 6000)
    assert_equal 'prompt_too_large', error
    _, error, = LlmPrompt.run(:codex, ' ')
    assert_equal 'empty_prompt', error
  end
end

class HmacAuthTest < Minitest::Test
  def setup
    @env = ENV.to_h
    @secret = HmacAuth.instance_variable_get(:@secret)
    HmacAuth.instance_variable_set(:@secret, 'test-only-key')
    %w[HTTP_X_TIMESTAMP HTTP_X_SIGNATURE HTTP_CF_CONNECTING_IP CF_ACCESS REDIRECT_CF_ACCESS].each { |key| ENV.delete(key) }
    ENV['REQUEST_METHOD'] = 'POST'
    ENV['REQUEST_URI'] = '/lib/api/tunnels.rb?name=neko'
    ENV['REMOTE_ADDR'] = '203.0.113.10'
    @body = '{"codex_prompt":"日本語 + %20"}'
  end

  def teardown
    ENV.replace(@env)
    HmacAuth.instance_variable_set(:@secret, @secret)
  end

  def sign
    ts = Time.now.to_i.to_s
    ENV['HTTP_X_TIMESTAMP'] = ts
    ENV['HTTP_X_SIGNATURE'] = HmacAuth.sign('test-only-key', 'POST', ENV['REQUEST_URI'], ts, @body).upcase
  end

  def test_raw_body_query_and_case_insensitive_signature
    sign
    assert_equal :hmac_ok, HmacAuth.authorize(@body)
    assert_equal :bad_signature, HmacAuth.authorize(@body + ' ')
    ENV['REQUEST_URI'] = '/lib/api/tunnels.rb'
    assert_equal :bad_signature, HmacAuth.authorize(@body)
  end

  def test_expired_and_bad_signatures_do_not_fall_back_to_local_ip
    ENV['REMOTE_ADDR'] = '127.0.0.1'
    sign
    ENV['HTTP_X_SIGNATURE'] = '0' * 64
    assert_equal :bad_signature, HmacAuth.authorize(@body)
    ENV['HTTP_X_TIMESTAMP'] = (Time.now.to_i - 301).to_s
    assert_equal :bad_timestamp, HmacAuth.authorize(@body)
  end

  def test_cloudflare_forwarding_does_not_appear_as_allowlisted_loopback
    ENV['REMOTE_ADDR'] = '127.0.0.1'
    ENV['HTTP_CF_CONNECTING_IP'] = '203.0.113.10'
    assert_equal :unauthorized, HmacAuth.authorize('')
    ENV['REMOTE_ADDR'] = '203.0.113.11'
    ENV['HTTP_CF_CONNECTING_IP'] = '127.0.0.1'
    assert_equal :unauthorized, HmacAuth.authorize('')
  end

  def test_llm_requests_require_hmac_even_on_loopback
    ENV['REMOTE_ADDR'] = '127.0.0.1'
    previous = $stdout
    $stdout = StringIO.new
    assert_nil HmacAuth.enforce!(@body, require_hmac: true)
    assert_includes $stdout.string, '401 Unauthorized'
    sign
    assert_equal @body, HmacAuth.enforce!(@body, require_hmac: true)
  ensure
    $stdout = previous
  end

  def test_protected_requests_preserve_signature_failure_reason
    sign
    ENV['HTTP_X_SIGNATURE'] = '0' * 64
    previous = $stdout
    $stdout = StringIO.new
    assert_nil HmacAuth.enforce!(@body, require_hmac: true)
    assert_includes $stdout.string, '"reason":"bad_signature"'
  ensure
    $stdout = previous
  end
end
