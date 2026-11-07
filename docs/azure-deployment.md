# Azure deployment notes

The app runs as three Docker Compose services (`docker-compose.yml`): `db` (PostgreSQL), `api` (FastAPI, `server/Dockerfile`) and `web` (nginx serving the built React site and forwarding `/api`, `web/Dockerfile`). Only `web` is published, on port 8000.
The existing Azure OpenAI deployment can be reused through environment variables.

## Recommended first deployment: one Linux VM

Run the whole compose stack on the VM. PostgreSQL keeps its data in the `pgdata` volume, and the scheduler stays inside the `api` process.

1. Select the Azure subscription, resource group, region and spending limit before creating resources. A VM, persistent disk and public IP can incur charges.
2. Copy the source to the VM and run `./redeploy.sh` there (it runs `docker compose up -d --build`), so the images are built for the VM's architecture. To build elsewhere instead, set `DOCKER_DEFAULT_PLATFORM=linux/amd64` for a typical x64 VM; an Apple Silicon laptop otherwise builds ARM images. Supply secrets through `.env` on the VM or a secret manager; `.env` is excluded from the build contexts and must not be baked into an image.
3. Keep Docker's volumes (`pgdata`, `apidata`) on the VM's persistent OS or managed data disk, not its temporary disk or an Azure Files/network share. The services already restart automatically (`restart: unless-stopped`). Set `POSTGRES_PASSWORD` before the first start.
4. Choose whether to import existing data or start fresh. Back up PostgreSQL with `docker compose exec db pg_dump -U matchmaker matchmaker > backup.sql`, and restore by piping that file into `psql`. Keep the original as a backup.
5. Back up the database regularly, e.g. a cron job running the `pg_dump` command above.
6. Configure the chosen public hostname and HTTPS reverse proxy. Bind the published port 8000 to localhost (`"127.0.0.1:8000:80"` in `docker-compose.yml`) so only the proxy can reach it. Restrict SSH access to the operator's IP address. Set `PUBLIC_BASE_URL` to the final HTTPS URL so email and document links point at the deployed app.
7. Apply the chosen access policy. A public hackathon demo exposes paid AI research endpoints; decide on usage limits and whether email sending should be enabled. A private deployment needs an authentication layer such as Microsoft Entra ID through an appropriate proxy or hosting integration.
8. Verify the final HTTPS URL, `/api/meta`, grant search, a research run, source PDFs, saved decisions and persistence after a container restart. If reusing existing grant data, turn off sample seeding with `SEED_SAMPLE_IF_EMPTY=false` so a missing volume does not silently appear as a demo dataset.

`DATABASE_URL` is set by `docker-compose.yml` and overrides any value in `.env`. `DATA_DIR=/data` (the `apidata` volume) holds the email outbox when no mail server is configured.

Only enable the intended scheduler/email behavior. The scheduler runs inside the application process; multiple replicas or multiple serving revisions would duplicate scheduled jobs. Research job progress is held in memory, while completed research results are saved in the database. A restart interrupts active research jobs.

## Managed hosting: Container Apps or App Service

Deploy the `api` and `web` images, and use Azure Database for PostgreSQL instead of the `db` container:

- Set `DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB?sslmode=require` on the api. Container Apps' container/replica storage is temporary, so the database must not live inside it.
- Never fall back to SQLite here (an empty `DATABASE_URL`): its WAL mode does not work over a network filesystem such as Azure Files, and replica storage is lost on replacement.
- `web/nginx/default.conf` forwards `/api` to the host `api:8000`; change that to the api's internal address, or route `/api` with the platform's ingress instead.
- Initially keep a single replica, a nonzero minimum replica count and a single serving revision while background research jobs and scheduling remain in process. Move scheduled ingestion and job state to dedicated jobs/shared storage before adding replicas.

Sources: [SQLite WAL limitations](https://sqlite.org/wal.html), [Container Apps storage mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts), [Linux VM quickstart](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/quick-create-cli).

## Current environment requirements

- Azure CLI/account access is required to provision and inspect the chosen Azure resources. No signed-in Azure CLI profile was found during the deployment readiness check.
- Region, subscription, resource group, budget and public/private access policy still need to be selected.
- Existing environment variables are documented in `.env.example`. Provisioning Azure OpenAI again is unnecessary if the configured deployment is accessible from the hosted app.
