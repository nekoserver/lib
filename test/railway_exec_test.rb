# frozen_string_literal: true
require 'minitest/autorun'
require 'tmpdir'
require 'stringio'
require_relative '../api/railway_exec'
require_relative '../api/tunnels_lib'

class RailwayExecTest < Minitest::Test
  def test_message_routes
    assert_equal 'railway_list_services', RailwayExec.route('message' => 'railway_exec="railway_list_services"')
    assert_equal 'railway_list_services', RailwayExec.route('message' => 'railway_exec="railway%5Flist%5Fservices"')
    assert_equal 'railway_list_services', RailwayExec.route('message' => 'railway_exec=railway_list_services')
    assert_equal '', RailwayExec.route('message' => 'railway_exec="%GG"')
    assert_equal 'service list --json', RailwayExec.route('message' => 'railway_exec="service%20list%20--json"')
    assert_equal 'service list --json', RailwayExec.route('message' => 'railway_exec="service+list+--json"')
    assert_equal 'service list %20', RailwayExec.route('message' => 'railway_exec="service%20list%20%2520"')
    assert_nil RailwayExec.route('message' => 'railway_list_services')
    assert_nil RailwayExec.route('message' => 'ordinary question')
    assert_nil RailwayExec.route('message' => 'railway_uptime')
  end

  def test_only_fixed_read_commands
    RailwayExec::COMMANDS.each do |name, args|
      assert_equal args + ['--json'], RailwayExec.arguments(name)
      assert_equal args + ['--json'], RailwayExec.arguments(args.join(' '))
    end
    assert_equal %w[service list --environment production --json], RailwayExec.arguments('railway service list --environment production')
    assert_equal %w[service status --service api --environment production --json], RailwayExec.arguments('railway_get_service_status --service api --environment production')
    ['up', 'railway_list_services;id', 'railway_list_services --help',
     'railway_list_unknown', 'railway_exec="service list"', '',
     'service list; id', 'service list --help', 'service list --environment',
     'service list --environment --help', 'service delete api'].each do |value|
      assert_raises(ArgumentError) { RailwayExec.arguments(value) }
    end
  end

  def test_output_and_nonzero_exit
    previous = ENV['LIB_RAILWAY_BIN']
    Dir.mktmpdir do |dir|
      path = File.join(dir, 'railway')
      File.write(path, "#!/bin/sh\nprintf '%s\\n' \"$@\"\nexit 7\n")
      File.chmod(0o700, path)
      ENV['LIB_RAILWAY_BIN'] = path
      payload = RailwayExec.run('railway_list_services')
      assert_equal "service\nlist\n--json\n", payload['reply']
      assert_equal 'railway_list_services', payload['command']
      assert_equal 7, payload['exit_code']
      assert_equal 'failed', payload['ask_status']
    end
  ensure
    previous ? ENV['LIB_RAILWAY_BIN'] = previous : ENV.delete('LIB_RAILWAY_BIN')
  end

  def test_usage_read_commands_and_mutation_rejection
    assert_equal %w[usage --json], RailwayExec.arguments('railway usage')
    assert_equal %w[usage --period previous --workspace Acme --json], RailwayExec.arguments('usage --period previous --workspace Acme')
    assert_equal %w[usage projects --project api --json], RailwayExec.arguments('usage projects --project api')
    assert_equal %w[usage limit status --target agent --json], RailwayExec.arguments('usage limit status --target agent')
    assert_equal %w[usage --period previous --json], RailwayExec.arguments('railway_get_usage --period previous')
    assert_equal 'railway usage --period previous', RailwayExec.route('message' => 'railway_exec="railway%20usage%20--period%20previous"')
    ['usage limit set --target workspace --hard 100', 'usage limit update --soft 75',
     'usage limit remove --yes', 'usage --hard 100', 'usage limit status --period previous',
     'usage --workspace', 'usage projects; id'].each do |command|
      assert_raises(ArgumentError) { RailwayExec.arguments(command) }
    end
  end

  def test_loopback_still_requires_hmac
    previous_env = ENV.to_h
    previous_stdout = $stdout
    ENV['REQUEST_METHOD'] = 'GET'
    ENV['QUERY_STRING'] = 'message=railway_exec%3D%22railway_list_services%22'
    ENV['REQUEST_URI'] = '/lib/api/tunnels.rb?' + ENV['QUERY_STRING']
    ENV['REMOTE_ADDR'] = '127.0.0.1'
    %w[HTTP_X_TIMESTAMP HTTP_X_SIGNATURE].each { |key| ENV.delete(key) }
    $stdout = StringIO.new
    TunnelsLib.run!
    assert_includes $stdout.string, '401 Unauthorized'
  ensure
    ENV.replace(previous_env)
    $stdout = previous_stdout
  end
end
