# Public email subscriptions

Anyone can subscribe at `/subscribe`, without an account or email-domain restriction.
The email panel in the staff application also creates public subscriptions. Agency,
count (1–100), frequency and selected filters are retained. Public digests use
published agency mission profiles and grant listings only: internal plans,
projects, decisions and team feedback are excluded. Grant links go directly to
the public announcement rather than the staff application.

The Azure-managed sender still works; a custom government sender domain is not
required. `ALLOWED_EMAIL_DOMAINS=` leaves staff email actions unrestricted too;
public signup always accepts all syntactically valid email domains independently.

## Abuse protections

- Public signup requires double opt-in even if REQUIRE_EMAIL_CONFIRMATION=false.
  New settings are held separately until the recipient confirms. Repeated signup
  cannot overwrite a confirmed subscription without access to its mailbox.
- Confirmation tokens are random, single-use and expire after 24 hours. GET only
  displays a confirmation button, so mail scanners cannot activate subscriptions.
  Pending tokens are not returned by the signup API, including in outbox mode.
- Active subscriptions are capped at 10 per email address.
- Public digests do not call the chat model or expose staff-only matching context.
- Signup limits: 5/IP/hour, 3/recipient/hour and 100/service/hour. IP attempts also
  include honeypot submissions. Recipient keys are hashed in rate-limit storage.
- All API calls: 120/IP/minute and 600/service/minute, including invalid requests.
  Search/export/staff previews additionally share a 20/IP/minute budget.
- Staff test emails: 5/IP/hour, 3/recipient/hour and 50/service/hour; production
  tests remain limited to the signed-in user's address and authorized agency.
- Counters are persisted in SQLite with atomic transactions and a 24-hour
  retention window. They survive restarts and are shared by workers using the same
  database. They are not a distributed limiter across independent databases.
- HTTP 429 includes Retry-After. Public request bodies are capped at 16 KiB;
  staff bodies at 1.5 MB. Actual streamed bytes are counted, not only Content-Length.
  Query strings are capped at 4 KiB. Public signup requires JSON and rejects
  cross-origin writes. Honeypot, existing security headers, no-store API responses,
  and no-referrer token pages provide additional safeguards.
- Unsubscribe uses the random link token and requires POST to change state. It
  works without sign-in, including mail clients' one-click unsubscribe POSTs.
  Public confirmation and unsubscribe POSTs accept foreign or `null` Origin
  headers because their random tokens authorize the action. This supports
  privacy-isolated email browser tabs; signup and other writes still reject
  foreign origins. GET requests never confirm or unsubscribe a recipient.

Use one scheduler-enabled replica with the current SQLite deployment. For public
internet deployment, also apply edge/WAF rate limits and request/time limits so
traffic is limited before it reaches Python or SQLite. Configure trusted proxy
addresses in Uvicorn; do not trust arbitrary forwarded headers or use `*`. If the
proxy does not provide trusted client addresses, clients may share an IP budget.
An application limiter is not DDoS protection; the global budget intentionally
prioritizes bounding email cost over availability during distributed abuse.

## Azure Easy Auth exclusions

Keep staff authentication enabled. Set `globalValidation.excludedPaths` in the
Container Apps auth configuration to these exact paths (preserve other needed
probe exclusions):

```json
[
  "/healthz",
  "/subscribe",
  "/public-signup.js",
  "/api/public/subscription-options",
  "/api/public/subscriptions",
  "/api/public/subscriptions/confirm",
  "/api/subscriptions/unsubscribe"
]
```

Do not exclude `/api/*`, the staff subscription test endpoint or staff static
assets. The app independently checks path and HTTP method. These platform settings
must be applied by the deployment administrator; editing this repository does not
change Azure. See [Microsoft's auth configuration reference](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps-auth-configs/create-or-update?view=rest-resource-manager-containerapps-2026-07-01).

Set PUBLIC_BASE_URL to the exact HTTPS deployment origin before public use.
Localhost links work only on the computer running the app. Provider credentials
remain in `.env` or Azure secret references, never in the browser, repository or
confirmation URLs. Treat confirmation/unsubscribe link tokens as secrets and
redact URL query strings in production access logs.

## Smoke test

1. Open `/subscribe` while signed out. Choose an agency, grant count and frequency.
2. Submit an email from any domain. Expect a generic confirmation response, not
   subscription tokens or existing subscription status.
3. Open the emailed link. Clicking the button starts the public digest; refreshing
   or replaying the same link must not resend it.
4. Request different settings for the same address. The current settings must stay
   active until the new confirmation is clicked.
5. Check the digest and unsubscribe without signing in. Staff APIs must still
   return 401 to an anonymous caller.
6. Exceed a quota and confirm HTTP 429 and Retry-After. Automated tests use an
   isolated database and fake email transport; they do not send real email.
