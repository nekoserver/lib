#!/usr/bin/env ruby
# frozen_string_literal: true
# Sends the same signed request as the Worker's `/neko askgk <message>` to a tunnels CGI
# (submit once with wait_seconds 0, then poll the same ask_id) and prints the result.
#
#   ORIGIN_HMAC_SECRET=... ruby askgk_request.rb [cgi] [message] [max_polls]
#
# Defaults: cgi = lib/claude/api/tunnels.claude.rb, message = claude_prompt="hello".
# The secret is read from the environment and never printed. Exit status 0 only when
# the final ask_status is "done" with a reply.
require 'json'
require 'open3'
require_relative '../../../api/hmac_auth'

cgi = File.expand_path(ARGV[0] || File.join(__dir__, '../../api/tunnels.claude.rb'))
message = ARGV[1] || 'claude_prompt="hello"'
max_polls = Integer(ARGV[2] || 300)
secret = ENV['ORIGIN_HMAC_SECRET'].to_s.empty? ? ENV['HMAC_SECRET'].to_s : ENV['ORIGIN_HMAC_SECRET']
abort 'Set ORIGIN_HMAC_SECRET (or HMAC_SECRET)' if secret.empty?
path = '/lib/' + cgi.split('/lib/', 2).last.to_s

call = lambda do |payload|
  body = JSON.generate(payload)
  ts = Time.now.to_i.to_s
  env = { 'REQUEST_METHOD' => 'POST', 'REQUEST_URI' => path, 'SCRIPT_NAME' => path,
          'CONTENT_TYPE' => 'application/json', 'CONTENT_LENGTH' => body.bytesize.to_s,
          'HTTP_X_TIMESTAMP' => ts, 'HTTP_X_SIGNATURE' => HmacAuth.sign(secret, 'POST', path, ts, body),
          'REMOTE_ADDR' => '203.0.113.9' }
  out, = Open3.capture2(env, cgi, stdin_data: body)
  head, json = out.split("\r\n\r\n", 2)
  result = JSON.parse(json.to_s) rescue { 'raw' => out }
  [head.to_s.lines.map(&:strip).reject(&:empty?), result]
end

started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
headers, result = call.call({ status: 'healthy', format: 'json', message: message, wait_seconds: 0 })
puts headers
max_polls.times do
  break unless %w[pending running].include?(result['ask_status'])
  sleep 1
  _, result = call.call({ format: 'json', ask_id: result['ask_id'] })
end
result.delete('tunnels')
puts JSON.pretty_generate(result)
puts format('elapsed: %.1fs', Process.clock_gettime(Process::CLOCK_MONOTONIC) - started)
exit(result['ask_status'] == 'done' && !result['reply'].to_s.empty? ? 0 : 1)
