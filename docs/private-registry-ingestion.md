# Private Registry Ingestion — GAMe 0.3.2.2

**Status:** The authenticated inventory push API is implemented. A production SaaS host, machine-to-machine client registration, and delivery operations are not provided by this prototype.

An authorized tenant `connection_admin` registers the provider **Private / Self-hosted Agent Registry** with an organization-local namespace such as `internal-platform`.

No SaaS pull access is required. A lightweight customer-hosted collector can use HTTPS to push inventory metadata to:

`POST https://<game-saas-host>/api/connections/<connection-id>/ingest`

Example JSON payload:

```json
{
  "agents": [
    {
      "external_id": "internal-platform/invoice-agent",
      "name": "Invoice review agent",
      "description": "An internal invoice review workflow",
      "provider_status": "running",
      "owner_email": "platform@example.org"
    }
  ]
}
```

The client must send an **OIDC Bearer access token issued for GAMe**, with the workload subject registered as a connection administrator in the authorized tenant. For subjects with memberships in multiple tenants, also send `X-GAME-Tenant: <authorized-tenant-id>`. The server validates the token and membership; a tenant header alone grants no access. In the legacy `local` development bypass, requests are restricted to loopback and the bypass must be explicitly enabled with `GAME_ALLOW_INSECURE_LOCAL=true`. Prefer OIDC API mode for testing the workload push flow.

Records are upserted using `(connection_id, external_id)`; the API accepts 1–500 agents per request, rejects duplicate external IDs within a batch and never imports code, secrets, prompts or model outputs. A successful push updates discovery metadata, **not** runtime activity or financial telemetry.

Production use still requires a supported customer collector, machine-to-machine identity registration and lifecycle, per-tenant rate limits, delivery/retry handling, operational monitoring, and security review. Do not treat this endpoint description as evidence that a production SaaS host is available.
