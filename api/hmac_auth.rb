# frozen_string_literal: true
# HMAC-SHA256 request authentication for /lib/api CGI.
# Secret sources (first non-empty wins):
#   1. /etc/apache2/secrets/origin-hmac  (mode 640 root:www-data)
#   2. ENV ORIGIN_HMAC_SECRET or HMAC_SECRET
#   3. sudo -u box /usr/local/libexec/origin-hmac-secret-read
#      → /home/box/.config/origin-hmac-secret
#
# Headers:
#   X-Timestamp  Unix seconds
#   X-Signature  hex HMAC-SHA256 of:
#     METHOD\nPATH\nTIMESTAMP\nSHA256_HEX(body)
#   PATH = request path + query string as received (CGI REQUEST_URI).
#   GET body = empty string.
# Skew: reject if |now - ts| > 300.
require "openssl"
require "ipaddr"
require "open3"
require "json"

module HmacAuth
  SKEW_SECONDS = 300
  APACHE_SECRET = "/etc/apache2/secrets/origin-hmac"
  BOX_SECRET_HELPER = "/usr/local/libexec/origin-hmac-secret-read"

  # Mirror conf-available/ip-allowlist.conf (+ loopback).
  ALLOWLIST_CIDRS = [
    "49.96.0.0/12",
    "1.72.0.0/14",
    "160.249.0.0/16",
    "240a:61::/32",
    "127.0.0.0/8",
    "::1/128"
  ].freeze

  module_function

  def load_secret
    return @secret if defined?(@secret) && @secret

    s = read_file_secret(APACHE_SECRET)
    s = ENV["ORIGIN_HMAC_SECRET"].to_s.strip if s.nil? || s.empty?
    s = ENV["HMAC_SECRET"].to_s.strip if s.nil? || s.empty?
    if s.nil? || s.empty?
      out, status = Open3.capture2("sudo", "-n", "-u", "box", BOX_SECRET_HELPER)
      s = status.success? ? out.to_s.strip : ""
    end
    @secret = s.to_s.strip
    @secret = nil if @secret.empty?
    @secret
  end

  def read_file_secret(path)
    File.read(path).to_s.strip
  rescue Errno::ENOENT, Errno::EACCES
    nil
  end

  def request_path
    uri = ENV["REQUEST_URI"].to_s
    return uri unless uri.empty?

    path = ENV["SCRIPT_NAME"].to_s + ENV["PATH_INFO"].to_s
    qs = ENV["QUERY_STRING"].to_s
    qs.empty? ? path : "#{path}?#{qs}"
  end

  def body_sha256_hex(body)
    OpenSSL::Digest::SHA256.hexdigest(body.to_s)
  end

  def signing_string(method, path, timestamp, body)
    "#{method.to_s.upcase}\n#{path}\n#{timestamp}\n#{body_sha256_hex(body)}"
  end

  def sign(secret, method, path, timestamp, body)
    OpenSSL::HMAC.hexdigest("SHA256", secret, signing_string(method, path, timestamp, body))
  end

  def secure_eq_hex(a, b)
    aa = a.to_s.downcase
    bb = b.to_s.downcase
    return false if aa.empty? || bb.empty? || aa.bytesize != bb.bytesize
    return false unless aa.match?(/\A[0-9a-f]+\z/) && bb.match?(/\A[0-9a-f]+\z/)

    OpenSSL.fixed_length_secure_compare(aa, bb)
  end

  def timestamp_ok?(ts_str, now = Time.now.to_i)
    ts = Integer(ts_str)
    (now - ts).abs <= SKEW_SECONDS
  rescue ArgumentError, TypeError
    false
  end

  def client_ip
    # After mod_remoteip, REMOTE_ADDR is CF-Connecting-IP when present.
    remote = ENV["REMOTE_ADDR"].to_s.strip
    forwarded = ENV["HTTP_CF_CONNECTING_IP"].to_s.strip
    # Only the local cloudflared connector can supply this forwarding header.
    return forwarded if %w[127.0.0.1 ::1].include?(remote) && !forwarded.empty?
    remote
  end

  def ip_allowlisted?(ip = client_ip)
    return false if ip.nil? || ip.empty?

    addr = IPAddr.new(ip)
    ALLOWLIST_CIDRS.any? { |cidr| IPAddr.new(cidr).include?(addr) }
  rescue IPAddr::InvalidAddressError
    false
  end

  # Returns :ok, :hmac_ok, :ip_ok, or a reason symbol for 401.
  def authorize(body)
    ts = ENV["HTTP_X_TIMESTAMP"].to_s.strip
    sig = ENV["HTTP_X_SIGNATURE"].to_s.strip
    method = ENV["REQUEST_METHOD"].to_s.upcase
    path = request_path
    secret = load_secret

    hmac_attempt = !ts.empty? && !sig.empty?
    if hmac_attempt
      return :missing_secret if secret.nil? || secret.empty?
      return :bad_timestamp unless timestamp_ok?(ts)

      expected = sign(secret, method, path, ts, body)
      return :hmac_ok if secure_eq_hex(expected, sig)

      return :bad_signature
    end

    return :ip_ok if ip_allowlisted?
    # Cloudflare Access JWT verified by Apache RewriteMap (cf-access-map) → env CF_ACCESS=ok
    return :jwt_ok if ENV["CF_ACCESS"].to_s == "ok" || ENV["REDIRECT_CF_ACCESS"].to_s == "ok"

    :unauthorized
  end

  def unauthorized_response!(reason)
    msg = {
      "error" => "unauthorized",
      "reason" => reason.to_s
    }
    print "Status: 401 Unauthorized\r\n"
    print "Content-Type: application/json; charset=utf-8\r\n"
    print "Cache-Control: no-store\r\n"
    print "\r\n"
    print JSON.generate(msg)
    print "\n"
  end

  # Call before consuming business logic. Returns body String if allowed, else nil (response sent).
  def enforce!(body, require_hmac: false)
    result = authorize(body)
    if require_hmac && result != :hmac_ok
      unauthorized_response!(:hmac_required)
      return nil
    end
    case result
    when :hmac_ok, :ip_ok, :jwt_ok, :ok
      body
    else
      unauthorized_response!(result)
      nil
    end
  end
end
