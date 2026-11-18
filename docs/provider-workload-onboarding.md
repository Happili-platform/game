# GAMe 0.3.2.2 — Provider Workload Onboarding

**Status:** AWS assume-role, Google service-account impersonation, and Microsoft shared-app connection modes are implemented. This guide covers their identity and permission prerequisites. Live provider validation and production SaaS readiness are separate requirements; this prototype is not a hosted commercial service.

Each provider connection targets an explicitly configured customer resource and is stored under an GAMe tenant. In a future hosted deployment, provider usage remains in the customer's cloud account; hosting and operational costs are separate concerns.

## AWS: customer cross-account IAM role

Choose `AWS Bedrock AgentCore` → `Cross-account IAM role (renewable)`.

1. Tenant connection administrator enters the AWS region and **customer role ARN**, saves the connection, and obtains the generated, per-connection **External ID** from the connection list. This value is not a password and cannot be edited.
2. The AWS customer IAM administrator creates a role in the customer's AWS account with `bedrock-agentcore:ListAgentRuntimes` (or `bedrock:ListAgents` for a separate Bedrock Classic connector). The role's trust policy names the **exact GAMe SaaS host IAM role** as principal and requires `sts:ExternalId` equal to the generated External ID.
3. The GAMe SaaS source IAM role must be authorized to `sts:AssumeRole` on the customer role ARN. The customer controls role permissions and can revoke trust at any time.
4. GAMe calls `AssumeRole` with a new 15-minute session for each discovery. The host workload's source identity must itself be renewable (ECS/EKS/EC2 task role, etc.). No human SSO or user-access keys are involved.

**Illustrative trust policy** (replace values with the actual SaaS host role ARN and displayed External ID):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::111122223333:role/GAMESaaSConnectorRole"},
    "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"sts:ExternalId": "<unique-external-id-from-game>"}}
  }]
}
```

The SaaS role principal above is fictitious. **Do not apply it unchanged.** Credentials will be renewable only after the SaaS host workload identity and cross-account trust are properly configured.

## Google: per-customer service account impersonation

Choose `Google Agent Engine` → `Service account impersonation (renewable)`.

1. Google customer creates `game-discovery@CUSTOMER_PROJECT.iam.gserviceaccount.com` or another dedicated service account.
2. Grant it an appropriate read-only role such as `roles/aiplatform.viewer` on the project/location, or narrower `aiplatform.reasoningEngines.list` custom permissions.
3. Grant the GAMe SaaS host workload identity `roles/iam.serviceAccountTokenCreator` **on that dedicated service account only**. Configure Google's IAM Credentials API and host ADC via a trusted workload identity; prefer federation to uploaded JSON keys.
4. Enter the exact service account email, customer project ID and location in the connection. The server gets a new short-lived impersonation token for each operation.

**Important:** Tenant-provided JSON credential-source URLs are not accepted for impersonation to prevent SSRF/credential theft. This connector uses only host-operator-configured ADC.

## Microsoft: shared multi-tenant Entra application

Choose `Microsoft Foundry` → `Shared SaaS Entra app (renewable tokens)`.

1. For a hosted deployment, the platform operator creates and verifies a multi-tenant Entra app. In the host environment configure `GAME_AZURE_CLIENT_ID` and `GAME_AZURE_CLIENT_SECRET` (development bridge; use workload federation or certificate in the production design).
2. The customer tenant administrator consents to the SaaS app, creating a service principal in their Entra tenant. Separately grant that service principal narrow Azure IAM rights for selected Foundry resources/projects.
3. The customer enters the **Entra tenant GUID** and Foundry project endpoint in GAMe. Each discovery requests a new OAuth access token for the customer tenant. No customer-provided Azure secret is stored in the connection.

The shared app credential is a centrally managed operational secret, not short-lived SSO session credentials. Rotate it, monitor failures and plan federated identity for a production release.

## Existing Legacy Connections

Previously created v0.2.x connections remain `auth_mode=legacy` in the `local-dev` tenant. Static credential execution is disabled when the server runs in OIDC API mode. Migrate connections individually to a supported workload mode when the required cloud IAM is configured; migrations do not rewrite existing connections automatically. Test the new connection before retiring the old one. For the legacy local credential workflow, see [provider-onboarding.md](provider-onboarding.md).
