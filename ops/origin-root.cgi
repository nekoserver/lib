#!/opt/rbenv/versions/4.0.7/bin/ruby
# Browser entry redirects to the dashboard; API requests require HMAC.
require '/app/lib/api/hmac_auth'
# A human browser can open the HTML shell without weakening API authentication.
html_request = ENV['REQUEST_METHOD'] == 'GET' &&
               ENV['HTTP_ACCEPT'].to_s.split(',').any? { |part| part.split(';').first.strip == 'text/html' } &&
               ENV['HTTP_X_TIMESTAMP'].to_s.empty? && ENV['HTTP_X_SIGNATURE'].to_s.empty?
if html_request
  print "Status: 302 Found\r\nLocation: /lib/dashboard/railway/\r\nCache-Control: no-store\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
  puts 'Open /lib/dashboard/railway/'
  exit
end
body = STDIN.read
exit unless HmacAuth.enforce!(body, require_hmac: true)
print "Content-Type: application/json; charset=utf-8\r\n"
print "Cache-Control: no-store\r\n\r\n"
print JSON.generate({status: 'ok'}) + "\n"
