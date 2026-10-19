require 'minitest/autorun'
require 'tmpdir'
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
  def test_both_config_keys_authenticate_and_missing_primary_falls_back
    Dir.mktmpdir do |dir|
      primary = File.join(dir, 'primary.env')
      fallback = File.join(dir, 'fallback.env')
      File.write(primary, "ORIGIN_HMAC_SECRET='primary key'\n")
      File.write(fallback, "ORIGIN_HMAC_SECRET='fallback key'\n")
      HmacAuth.stub(:secret_files, [primary, fallback]) do
        ENV['REMOTE_ADDR'] = '203.0.113.1'
        ENV['REQUEST_METHOD'] = 'POST'
        ENV['REQUEST_URI'] = '/lib/api/tunnels'
        ENV['HTTP_X_TIMESTAMP'] = Time.now.to_i.to_s
        ['primary key', 'fallback key'].each do |key|
          ENV['HTTP_X_SIGNATURE'] = HmacAuth.sign(key, 'POST', ENV['REQUEST_URI'], ENV['HTTP_X_TIMESTAMP'], '{}')
          assert_equal :hmac_ok, HmacAuth.authorize('{}')
          assert_equal :bad_signature, HmacAuth.authorize('changed')
        end
        File.delete(primary)
        assert_equal :hmac_ok, HmacAuth.authorize('{}')
        File.write(fallback, "ORIGIN_HMAC_SECRET=\n")
        assert_equal :missing_secret, HmacAuth.authorize('{}')
      end
    end
  end

end
