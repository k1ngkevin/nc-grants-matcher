# Production email domain setup

The Azure-managed sender is working for development. A government sender domain
has not yet been provisioned or verified. NC IT must approve the domain and make
the DNS changes below; changing SMTP_FROM alone does not verify a domain.

## Required inputs

- Approved sending domain or subdomain and MailFrom address.
- Azure subscription, resource group, Email Communication Services resource,
  and the Communication Services resource used by this app.
- An administrator who can edit that domain's public DNS records.

## Provision and verify

1. In Email Communication Services > Provision domains, add the approved custom
   domain. Copy Azure's exact domain verification TXT record into public DNS.
2. Copy the SPF TXT and both DKIM CNAME records Azure generates into DNS.
   Use those generated values, not sample records. If the DNS name already has
   an SPF record, have the DNS administrator merge the authorized senders into
   one valid SPF policy rather than adding a second SPF record.
3. In Azure, verify domain ownership, SPF, DKIM and DKIM2. Wait for all checks to
   succeed. DNS propagation can delay verification.
4. Connect the verified email domain to the app's Communication Services resource.
   Create or select an approved MailFrom sender on that domain.
5. Have NC IT review the existing DMARC policy and SPF/DKIM alignment before
   changing it. Do not replace a government-wide policy or relax enforcement for
   this application. Use an IT-approved reporting address if configuring reports.
6. Set SMTP_FROM to the exact verified MailFrom address. Keep the connection
   string in the local ignored `.env`, or a Container Apps secret referenced by
   ACS_CONNECTION_STRING in production. Never commit credentials.
7. Set PUBLIC_BASE_URL to the deployed HTTPS website origin, and restrict
   ALLOWED_EMAIL_DOMAINS= to allow any recipient. Public signup always accepts
   all email domains and uses mandatory email confirmation and rate limits;
   see [public subscriptions](public-subscriptions.md). This does not replace
   Entra controls for staff APIs.
   Restart the backend after local environment changes.

## Verify delivery

Run `python server/send_test_email.py --to <approved-test-recipient>` from the
repository root (install `server/requirements-email-test.txt` first), then use
the app's **Send me a test email** with the chosen agency, filters and grant count.
The standalone script sends a fixed transport test; the app sends ranked grants.

Check the received message's original headers for SPF, DKIM and DMARC passes and
the expected From domain. Confirm links point to the deployed website. Check
Azure delivery logs and the recipient inbox/spam folder; API acceptance is not
proof of inbox delivery. Domain authentication improves sender trust but does not
guarantee inbox placement. For daily subscriptions, confirm the subscription and
keep the scheduler-enabled backend running.

## Microsoft references

- [Add and verify custom domains](https://learn.microsoft.com/azure/communication-services/quickstarts/email/add-custom-verified-domains)
- [Sender authentication best practices](https://learn.microsoft.com/en-us/azure/communication-services/concepts/email/email-authentication-best-practice)
- [Troubleshoot DNS verification](https://learn.microsoft.com/en-us/azure/communication-services/concepts/email/email-domain-configuration-troubleshooting)
