# frozen_string_literal: true
require 'json'
require 'timeout'
require 'tempfile'
require 'uri'
require 'shellwords'

module RailwayExec
  COMMANDS = {
    'railway_get_usage' => %w[usage],
    'railway_list_project_usage' => %w[usage projects],
    'railway_get_usage_limits' => %w[usage limit status],
    'railway_get_status' => %w[status],
    'railway_get_service_status' => %w[service status],
    'railway_list_environments' => %w[environment list],
    'railway_list_cloud_agents' => %w[ca list],
    'railway_whoami' => %w[whoami],
    'railway_list_projects' => %w[project list],
    'railway_list_services' => %w[service list],
    'railway_list_deployments' => %w[deployment list],
    'railway_list_domains' => %w[domain list],
    'railway_list_buckets' => %w[bucket list]
  }.transform_values(&:freeze).freeze
  VALUE_FLAGS = %w[--project --environment --service -p -e -s --limit].freeze
  module_function

  def route(filters)
    match = filters['message'].to_s.match(/\Arailway_exec=(.*)\z/m)
    return nil unless match
    value = match[1]
    if value.length >= 2 && [['"', '"'], ['“', '”']].any? { |left, right| value.start_with?(left) && value.end_with?(right) }
      value = URI.decode_www_form_component(value[1...-1])
    end
    value
  rescue ArgumentError
    ''
  end

  def arguments(value)
    return COMMANDS[value] + ['--json'] if COMMANDS.key?(value)
    tokens = Shellwords.shellsplit(value)
    tokens = COMMANDS[tokens.first] + tokens.drop(1) if COMMANDS.key?(tokens.first)
    tokens.shift if tokens.first == 'railway'
    command = COMMANDS.values.sort_by { |args| -args.length }.find { |args| tokens.first(args.length) == args }
    raise ArgumentError unless command
    value_flags = if command == %w[usage]
      %w[--workspace --period]
    elsif command == %w[usage projects]
      %w[--workspace --period --project --limit]
    elsif command == %w[usage limit status]
      %w[--workspace --target]
    else
      VALUE_FLAGS
    end
    rest = tokens.drop(command.length)
    until rest.empty?
      flag = rest.shift
      next if flag == '--json'
      raise ArgumentError unless value_flags.include?(flag)
      argument = rest.shift
      raise ArgumentError if argument.nil? || argument.empty? || argument.start_with?('-')
    end
    tokens << '--json' unless tokens.include?('--json')
    tokens
  end

  def run(value)
    args = arguments(value)
    env = { 'NO_COLOR' => '1', 'RAILWAY_CALLER' => 'skill:use-railway@1.6.1',
            'RAILWAY_AGENT_SESSION' => "railway-exec-#{Process.pid}" }
    pid = nil
    Tempfile.create('railway-exec') do |output|
      pid = Process.spawn(env, ENV.fetch('LIB_RAILWAY_BIN', '/usr/local/bin/railway'), *args,
                          in: File::NULL, out: output, err: output, pgroup: true)
      _, status = Timeout.timeout(20) { Process.wait2(pid) }
      pid = nil
      output.rewind
      text = output.read(16_384).to_s.force_encoding('UTF-8').scrub
      text += "\n...(truncated)" if output.size > 16_384
      payload = { 'command' => value, 'via' => 'railway', 'reply' => text,
                  'exit_code' => status.exitstatus, 'ask_status' => status.success? ? 'done' : 'failed' }
      payload['ask_error'] = 'railway_execution_failed' unless status.success?
      payload
    end
  rescue ArgumentError
    failure('railway_command_not_allowed', '対応するコマンド名を指定してください。例: railway_exec="railway_list_services"')
  rescue Timeout::Error
    failure('railway_timeout', 'Railway コマンドが20秒以内に完了しませんでした。')
  rescue SystemCallError
    failure('railway_unavailable', 'Railway CLI を実行できません。CGI の実行環境を確認してください。')
  ensure
    if pid
      begin
        Process.kill('KILL', -pid)
        Process.wait(pid)
      rescue Errno::ESRCH, Errno::ECHILD
        nil
      end
    end
  end

  def failure(error, reply)
    { 'command' => 'railway_exec', 'via' => 'railway', 'ask_status' => 'failed', 'ask_error' => error, 'reply' => reply }
  end
end
