# Azure deployment notes

The app is containerized: the Dockerfile builds React and serves it with FastAPI on port 8000.
The existing Azure OpenAI deployment can be reused through environment variables.

## Recommended first deployment: one Linux VM

This preserves the current SQLite database, notice attachments, saved AI results and in-process scheduler without a database rewrite.

1. Select the Azure subscription, resource group, region and spending limit before creating resources. A VM, persistent disk and public IP can incur charges.
2. Build a Linux image for the VM architecture. For a typical x64 VM, use `docker build --platform linux/amd64 -t nc-grants-matcher:azure-review .`. A build on an Apple Silicon laptop otherwise defaults to ARM unless configured differently.
3. Transfer the image or build the source on the VM. Supply secrets through a separate environment file or a secret manager; `.env` and related credentials must not be included in the image/build context.
4. Run one container with a persistent Docker volume or host directory mounted at `/data`. That storage must reside on the VM's persistent OS or managed data disk, not its temporary disk or an Azure Files/network share. Set a restart policy.
5. Choose whether to import the current database or initialize a new one. For an existing live SQLite database, make a consistent backup using SQLite's backup API, or stop writers and copy the full data directory. Copying only `matchmaker.db` while it is being written can omit transactions still in the WAL. Keep the original copy as a backup.
6. Configure the chosen public hostname and HTTPS reverse proxy. Bind the app's port 8000 to localhost or an internal container network. Restrict SSH access to the operator's IP address. Set `PUBLIC_BASE_URL` to the final HTTPS URL so email and document links point at the deployed app.
7. Apply the chosen access policy. A public hackathon demo exposes paid AI research endpoints; decide on usage limits and whether email sending should be enabled. A private deployment needs an authentication layer such as Microsoft Entra ID through an appropriate proxy or hosting integration.
8. Verify the final HTTPS URL, `/api/meta`, grant search, a research run, source PDFs, saved decisions and persistence after a container restart. If reusing existing grant data, turn off sample seeding with `SEED_SAMPLE_IF_EMPTY=false` so a missing volume does not silently appear as a demo dataset.

`DATA_DIR=/data` is already set by the Dockerfile. Unless deliberately overridden, `DB_PATH` resolves to `/data/matchmaker.db`, and notice attachments/outbox files also use this directory. Do not retain a laptop-specific `DB_PATH` in the cloud environment.

Only enable the intended scheduler/email behavior. The scheduler runs inside the application process; multiple replicas or multiple serving revisions would duplicate scheduled jobs. Research job progress is held in memory, while completed research results are saved in SQLite. A restart interrupts active research jobs.

## Managed hosting: Container Apps or App Service

The container can run on these services, but durable storage needs a change first:

- The app currently opens SQLite in WAL mode. SQLite explicitly states that WAL does not work over a network filesystem. Mounting Azure Files at `/data` is therefore not an appropriate database deployment for the current configuration.
- Container Apps' container/replica storage is temporary. Putting the database there risks losing grants, decisions and cached research when the replica is replaced.
- Migrate database access to PostgreSQL for a durable managed deployment. Notice PDF files can use a separate supported storage solution.
- Initially keep a single replica, a nonzero minimum replica count and a single serving revision while background research jobs and scheduling remain in process. Move scheduled ingestion and job state to dedicated jobs/shared storage before adding replicas.

Sources: [SQLite WAL limitations](https://sqlite.org/wal.html), [Container Apps storage mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts), [Linux VM quickstart](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/quick-create-cli).

## Current environment requirements

- Azure CLI/account access is required to provision and inspect the chosen Azure resources. No signed-in Azure CLI profile was found during the deployment readiness check.
- Region, subscription, resource group, budget and public/private access policy still need to be selected.
- Existing environment variables are documented in `.env.example`. Provisioning Azure OpenAI again is unnecessary if the configured deployment is accessible from the hosted app.
