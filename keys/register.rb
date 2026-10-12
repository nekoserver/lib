#!/opt/rbenv/versions/4.0.7/bin/ruby
# frozen_string_literal: true
require 'json'
require 'socket'
require 'timeout'
require_relative '../api/hmac_auth'

def reply(status, payload)
  print "Status: #{status}\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n\r\n"
  puts JSON.generate(payload)
end
if ENV['REQUEST_METHOD'] != 'POST'
  reply('405 Method Not Allowed', error: 'use_post')
  exit
end
length = ENV['CONTENT_LENGTH'].to_i
unless length.between?(1, 4096)
  reply('413 Payload Too Large', error: 'invalid_body_size')
  exit
end
body = STDIN.read(length)
exit unless HmacAuth.enforce!(body, require_hmac: true)
begin
  data = JSON.parse(body)
  raise ArgumentError unless data.is_a?(Hash) && data.keys == ['public_key'] && data['public_key'].is_a?(String)
  payload = Timeout.timeout(5) do
    UNIXSocket.open('/run/lib-ssh-keys/worker.sock') do |socket|
      socket.puts(JSON.generate('public_key' => data['public_key']))
      line = socket.gets(4097)
      raise IOError if line.nil? || line.bytesize > 4096
      JSON.parse(line)
    end
  end
  if payload['error'] == 'invalid_rsa_public_key'
    reply('400 Bad Request', payload)
  elsif payload['error']
    reply('503 Service Unavailable', payload)
  else
    reply('200 OK', payload)
  end
rescue JSON::ParserError, ArgumentError
  reply('400 Bad Request', error: 'invalid_request')
rescue SystemCallError, IOError, Timeout::Error
  reply('503 Service Unavailable', error: 'registration_unavailable')
end
