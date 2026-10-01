#!/home/box/.rbenv/versions/4.0.7/bin/ruby
# frozen_string_literal: true
# Filter CGI → HTML fragment for SSI (#exec cgi="tunnels-filter.rb").
# Inherits QUERY_STRING from parent .shtml (status / name filters).
# Allowlisted fields only.
require_relative "tunnels_lib"
TunnelsLib.run!(default_format: "html", force_format: "html")
