# NC staff access

The repository implements agency authorization. Deployment still requires an NC
identity administrator to configure the real tenant, app registration and groups.
An email suffix is not used as proof of employment.

## Azure setup

1. Confirm the tenant UUID and approved staff with NC IT. For this implementation
   use a single tenant; workers from other tenants need approved guest accounts.
2. Register a single-tenant Entra application. In Azure Container Apps >
   Authentication, add Microsoft Entra ID using that registration. Use the
   tenant-specific issuer `https://login.microsoftonline.com/<TENANT-ID>/v2.0`.
   Configure the client ID, client secret using a Container Apps secret reference,
   and callback `https://<APP-HOST>/.auth/login/aad/callback`.
3. Require authentication for staff requests, with only the public exclusions in
   [the public signup guide](public-subscriptions.md). Use the Microsoft sign-in redirect
   for the staff browser. Require HTTPS and restrict accepted token audiences to this
   application. Do not add Graph or unrelated application audiences.
4. Under the app registration's App roles, create enabled roles with allowed
   member type **Users/Groups**. Values must match exactly:
   - `Agency.deq`, `Agency.dhhs`, etc.: one role per agency ID in
     `server/app/agencies.py`. Each grants read/write access only to that agency.
   - `Matchmaker.Admin`: all agencies, metrics and manual ingest. Assign sparingly.
5. Under Enterprise applications > this app > Properties set **Assignment required**
   to **Yes**. Under Users and groups, assign IT-managed agency staff groups to
   their corresponding agency roles. Assign administrators to `Matchmaker.Admin`.
   If group assignment is unavailable under your license, assign individual users.
   A user may have multiple agency roles. Group membership must be managed by IT;
   tenant membership by itself does not grant application access.
6. Set these Container Apps environment variables (do not deploy local `.env`
   authentication defaults):

   ```text
   APP_ENV=production
   AUTH_MODE=entra
   ENTRA_TENANT_ID=<approved-tenant-UUID>
   PUBLIC_BASE_URL=https://<APP-HOST>
   ```

7. Route ALL traffic through the Container Apps authenticated ingress. Never
   expose Uvicorn directly, through another proxy, TCP ingress or a published
   container port. The app relies on Easy Auth stripping external
   `X-MS-CLIENT-PRINCIPAL*` headers and injecting its verified identity. The
   `CONTAINER_APP_NAME` startup check catches accidental local use; it is not
   cryptographic proof of the proxy. Do not set it manually outside Azure.
8. Configure HTTP readiness/liveness probes for `/healthz`, the only anonymous
   backend path. If Easy Auth intercepts the probe, configure only this exact
   path as an authentication exclusion; never exclude `/api` or static content.
9. Apply IT's Conditional Access/MFA policy to the enterprise app. Coordinate
   secret expiry/rotation and user removal with the identity administrator.

No token store is required: the backend uses the platform's verified principal
claims, checks the exact tenant and requires a known agency role or admin role.
The browser uses the platform session cookie and same-origin API requests.
The frontend only lists agencies authorized for that signed-in user.

## Verification before launch

- Anonymous staff-site browser: redirected to Microsoft sign-in. Anonymous callers
  cannot access staff API data. Public signup works at `/subscribe` without sign-in.
- Wrong tenant, unassigned staff and staff without an agency role: denied.
- DEQ role: DEQ search, export, projects, documents, decisions and subscriptions
  work; equivalent DHHS calls, including direct API calls and DELETE, return 403.
- Admin: metrics and manual ingest work without an API key. Ordinary staff get 403.
- Forged principal headers sent to the public ingress must not grant access.
- Sign out at `/.auth/logout`; sign back in after changing assignments. Existing
  sessions may retain role claims until renewed; revocation is not instantaneous.
- Cross-origin writes are rejected. Serve the frontend and API on the configured
  public origin; set PUBLIC_BASE_URL to that exact origin without a trailing slash.

Public subscription confirmation and token-based unsubscribe work without sign-in.
Staff subscription confirmation still requires sign-in and agency membership.
Exclude only the specific paths in [the public signup guide](public-subscriptions.md)
from Easy Auth; do not broadly exempt `/api` or disable staff authentication.

## Local development

`AUTH_MODE=development` is the default for Python development and preserves the
existing workflow. It grants anonymous access and must stay local. Startup refuses
development mode when APP_ENV is production or CONTAINER_APP_NAME is present.
The Docker image defaults to production/entra and needs the Azure configuration
above. For an explicit local container demo, override both APP_ENV=development
and AUTH_MODE=development and bind its published port only to 127.0.0.1.

## References

- [Container Apps authentication and trusted identity headers](https://learn.microsoft.com/en-us/azure/container-apps/authentication)
- [Entra provider configuration](https://learn.microsoft.com/en-us/azure/container-apps/authentication-entra)
- [Restrict an application to assigned users](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users)
