#!/opt/rbenv/versions/4.0.7/bin/ruby
# frozen_string_literal: true
require 'json'
require 'time'
require_relative '../../api/hmac_auth'
Encoding.default_external = Encoding::UTF_8

if ENV['REQUEST_METHOD'] != 'GET'
  print "Status: 405 Method Not Allowed\r\nAllow: GET\r\nContent-Type: application/json\r\n\r\n{\"error\":\"use_get\"}"
  exit
end
exit unless HmacAuth.enforce!('')
begin
  path = ENV.fetch('LIB_DAEMON_CACHE', '/var/cache/lib-api/daemons.json')
  payload = JSON.parse(File.read(path, encoding: 'UTF-8'))
  age = [Time.now - Time.iso8601(payload.fetch('checked_at')), 0].max.round
  payload['snapshot_age_seconds'] = age
  payload['stale'] = age > 60
  print "Content-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n\r\n"
  puts JSON.generate(payload)
rescue SystemCallError, JSON::ParserError, KeyError, ArgumentError
  print "Status: 503 Service Unavailable\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n"
  puts JSON.generate('error' => 'snapshot_unavailable', 'reply' => '稼働データを取得できません。収集プロセスを確認してください。')
end
