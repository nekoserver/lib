# PKCS#8 SSH key page

URL: `/lib/keys/`. RSA 3072/4096 key generation, PKCS#8 private PEM,
SPKI public PEM, and OpenSSH public keys run in the browser via Web Crypto.
No key material is stored in browser storage. Only the public key is POSTed
when the user explicitly registers it. The private key is unencrypted.

Registration requires the existing `api/hmac_auth.rb` HMAC authentication,
even from an allowlisted IP. `keys/register.rb` invokes a narrowly scoped root
helper over a local Unix socket. The worker accepts only bare RSA keys with exponent 65537
and 3072/4096 bits, appends to `/root/.ssh/authorized_keys` under a lock,
and preserves existing keys. It does not accept a target path or arguments.
Duplicate keys are not added, including keys with existing restrictions.

Install as root on the VM (CGI and `/lib/` Apache alias must already exist):

```sh
install -o root -g root -m 644 /app/lib/ops/ssh_key_register.py /usr/local/libexec/lib-ssh-key-register.py
install -o root -g root -m 755 /app/lib/ops/ssh_key_worker.py /usr/local/libexec/lib-ssh-key-worker.py
setsid -f /usr/bin/python3 /usr/local/libexec/lib-ssh-key-worker.py >/var/log/lib-ssh-key-worker.log 2>&1
```

The installed worker and helper must remain root-owned and not writable by www-data.
Updates require reinstalling the files and restarting the worker. The socket
accepts only the www-data UID (SO_PEERCRED); CGI requires a signed HMAC request.
Add lib-ssh-key-worker to the worker list in /app/start-web.sh to restart on wake. Clearing the page clears its displayed
keys; it does not revoke already registered keys or delete downloaded files.

Checks: `node --check keys/keygen.js`, `ruby -c keys/register.rb`,
`python3 -m unittest discover -s test -p ssh_key_register_test.py`.
