# Wake 参謀 via webhook

1. In Grok Bot chat, open the chip **Webhook URL** for routine `lib-api-ask` (do not paste the `grokbot://` deep link itself).
2. Copy the https URL (includes key).
3. Hand it to 参謀 via the secure secret form as `LIB_API_ASK_WEBHOOK`.
4. 参謀 writes it to `/etc/apache2/secrets/lib-api-ask-webhook`.

Then POST `message` that is NOT an allowlisted command → CGI fires webhook → 参謀 writes `resp-*.json` → same HTTP returns `reply`.
