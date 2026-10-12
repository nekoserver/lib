# Browser entry and root API

`ops/origin-root.cgi` is installed at `/usr/local/libexec/origin-root.cgi` on
this VM. Apache's existing `ScriptAliasMatch ^/$` executes it.

A GET with `Accept: text/html` and no HMAC headers redirects to
`/lib/dashboard/railway/`. The dashboard HTML shell contains no operational
data; its status endpoint retains authentication.

All other root requests retain the existing HMAC-only protocol and
`{"status":"ok"}` JSON response. A request with either signature header is
never treated as an unsigned browser request, even if it accepts HTML.

Install (requires the existing Ruby interpreter and `/app/lib/api/hmac_auth.rb`):

```sh
install -m 0755 ops/origin-root.cgi /usr/local/libexec/origin-root.cgi
```

The CGI-only change does not require restarting Apache. This entry links to the
daemon dashboard added in PR #56; that dashboard must be present at the target.

Verified publicly: browser GET redirects and opens the dashboard; unsigned JSON
and invalid-signature HTML return 401; correctly signed root JSON returns 200.
