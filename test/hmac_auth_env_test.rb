require 'minitest/autorun'
require 'minitest/mock'
require_relative '../api/hmac_auth'

class HmacAuthEnvTest < Minitest::Test
  def setup
    @env = ENV.to_h
    HmacAuth.remove_instance_variable(:@secret) if HmacAuth.instance_variable_defined?(:@secret)
    ENV.delete('ORIGIN_HMAC_SECRET')
    ENV.delete('HMAC_SECRET')
  end

  def teardown
    ENV.replace(@env)
    HmacAuth.remove_instance_variable(:@secret) if HmacAuth.instance_variable_defined?(:@secret)
  end

  def test_environment_priority_and_normalization
    ENV['ORIGIN_HMAC_SECRET'] = " origin-key \n"
    ENV['HMAC_SECRET'] = 'other-key'
    assert_equal 'origin-key', HmacAuth.load_secret
  end

  def test_blank_origin_falls_back_to_legacy_environment
    ENV['ORIGIN_HMAC_SECRET'] = ' '
    ENV['HMAC_SECRET'] = ' fallback-key '
    assert_equal 'fallback-key', HmacAuth.load_secret
  end

  def test_missing_environment_does_not_read_a_file
    File.stub(:read, ->(*) { flunk 'must not read a secret file' }) do
      assert_nil HmacAuth.load_secret
    end
  end

  def test_signed_request_matches_environment_key_and_rejects_other_key
    ENV['ORIGIN_HMAC_SECRET'] = 'configured-key'
    ENV['REMOTE_ADDR'] = '203.0.113.1'
    ENV['REQUEST_METHOD'] = 'POST'
    ENV['REQUEST_URI'] = '/lib/api/tunnels.rb'
    ENV['HTTP_X_TIMESTAMP'] = Time.now.to_i.to_s
    body = '{"message":"test"}'
    ENV['HTTP_X_SIGNATURE'] = HmacAuth.sign('configured-key', 'POST', ENV['REQUEST_URI'], ENV['HTTP_X_TIMESTAMP'], body)
    assert_equal :hmac_ok, HmacAuth.authorize(body)
    ENV['HTTP_X_SIGNATURE'] = HmacAuth.sign('other-key', 'POST', ENV['REQUEST_URI'], ENV['HTTP_X_TIMESTAMP'], body)
    assert_equal :bad_signature, HmacAuth.authorize(body)
  end
end
