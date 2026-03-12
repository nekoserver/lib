#!/usr/bin/env ruby
require 'cgi'
require 'date'

cgi = CGI.new
year = cgi['year'].to_i
month = cgi['month'].to_i

today = Date.today
year = today.year if year <= 0
month = today.month if month <= 0 || month > 12

begin
  first = Date.new(year, month, 1)
  last = Date.new(year, month, -1)
rescue ArgumentError
  first = Date.new(today.year, today.month, 1)
  last = Date.new(today.year, today.month, -1)
  year = first.year
  month = first.month
end

header = "#{year}年#{month}月"
weekdays = %w(日 月 火 水 木 金 土)

lines = []
lines << header
lines << weekdays.join(' ')

line = '   ' * first.wday
day = first
while day <= last
  line << day.day.to_s.rjust(2) << ' '
  day = day.next
  if day.wday == 0
    lines << line.rstrip
    line = ''
  end
end
lines << line.rstrip unless line.strip.empty?

puts "Content-Type: text/plain"
puts
lines.each { |l| puts l.rstrip }
