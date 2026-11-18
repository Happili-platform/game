# Provider Connections: Legacy Local Credentials

**Status:** This page documents the legacy static-credential workflow retained for local development and existing connections. Current release: GAMe 0.3.2.2. For renewable workload identity modes, use [provider-workload-onboarding.md](provider-workload-onboarding.md). Keep the password-authenticated application bound to `127.0.0.1`; this is not production credential management.

The legacy workflow below covers Microsoft Foundry, AWS, and Google connections that store credentials encrypted in the local database. Use narrowly scoped read permissions and development resources. Prefer renewable workload identity where available.

## Microsoft Foundry

1. Create a project and Entra application/service principal in your Azure development tenant.
2. Assign permissions to **read/list agents** at the authorized Foundry resource or project scope. Use a validated read-only role where available.
3. In GAMe → Provider connections, choose **Microsoft Foundry**, enter your Foundry project endpoint (e.g. `https://resource.services.ai.azure.com/api/projects/project`) and `AC_FOUNDRY` as prefix.
4. In Microsoft credentials, enter Tenant ID, Client ID, and the client secret **Value** (not secret ID). Save; then **Test connection** and **Discover now**.
5. Credentials are encrypted locally with a key separate from SQLite. Host-supplied `AC_FOUNDRY_AZURE_TENANT_ID`, `_CLIENT_ID` and `_CLIENT_SECRET`, or managed identity if configured, remain alternatives. Neither requires `az login` at runtime.

A 401 means identity/token may be invalid; 403 means missing authorization; zero discovered agents can be correct for an empty Foundry project.

## AWS AgentCore and Bedrock Agents Classic

1. Set up an AWS development account and an IAM Identity Center user or role authorized for your chosen account.
2. Grant `bedrock-agentcore:ListAgentRuntimes` to read AgentCore runtimes, or the applicable Bedrock Agents Classic read permissions for the legacy connector. Use read-only permissions; a discovery account need not be a deployer.
3. In the IAM Identity Center access portal, open **AWS accounts → your account → authorized permission set → Access keys / programmatic access**, and obtain temporary Access Key ID, Secret Access Key and Session Token.
4. In GAMe, choose **AWS Bedrock AgentCore**, enter the intended region (e.g. `us-west-2`), credential prefix `AC_AWS`, and all three temporary values. If available, enter their **expiration time** in local time to show a useful expired warning.
5. Save; **Test connection**; then **Discover now**. The access portal provides credentials without installing AWS CLI.

**Important:** Persisting an AWS SSO session token does **not** renew it. When it expires, return to IAM Identity Center, obtain renewed temporary credentials and use **Edit / credentials** to replace the encrypted values. To avoid manual renewal in enterprise deployment, use IAM workload roles / SDK credential chains rather than pasted tokens. A host profile `AC_AWS_AWS_PROFILE`, attached IAM role or normal AWS SDK environment credentials can be used instead of browser entry.

AgentCore discovery lists runtimes, not every Bedrock agent. An empty, successful listing means none were returned in the selected account and region.

## Google Cloud Agent Engine

1. Create a Google Cloud development project, enable the Vertex AI API, and select an Agent Engine supported location such as `us-central1`.
2. Create a service account with read access (`aiplatform.reasoningEngines.list`), using a scoped custom role or `roles/aiplatform.viewer` where appropriate.
3. Prefer ADC or workload identity federation. If your organization's policy allows a **development-only** service-account JSON key, it can be pasted into GAMe's Google credential form.
4. Choose **Google Agent Engine**, enter the actual **project ID** and **location**, set prefix `AC_GOOGLE`, save credentials if using the JSON option, then **Test connection** and **Discover now**.

The connector calls `reasoningEngines.list` for one project/location. Host ADC also remains supported via `GOOGLE_APPLICATION_CREDENTIALS` or a workload identity. No gcloud CLI is required for the service-account JSON option.

## Legacy Encrypted Credential Lifecycle

Browser-entered Microsoft, AWS and Google credentials are **encrypted in SQLite**, not held in ephemeral Python dictionaries. The AES-256-GCM key is generated separately in `~/.config/game/master.key` with owner-only permissions on the first save. Every encrypted record is bound to its provider ID and connection ID. The app never returns the secret values to browsers. Do not store the master key in the same backups as plaintext account data or commit it to version control.

- **Edit / credentials**: blank fields retain the existing encrypted credential; enter a complete new set to replace it.
- **Clear saved credentials**: deletes the encrypted copy for the connection; host SDK fallback may still be available.
- **Test connection**: uses persisted credentials after a restart, without importing inventory.
- **Discover now**: uses persisted credentials after a restart and writes only normalized local agent inventory.
- **Change project/region or environment prefix**: invalidates old saved credentials, resets sync state, and may clear local inventory after confirmation.
- **Expired AWS token**: an optional timestamp allows the dashboard to show expiry; real AWS responses also detect expired sessions. Manual tokens are never automatically refreshed.
- **Missing master key**: encrypted secrets are not silently overwritten or decrypted. Restore the original key file or deliberately delete the old encrypted records and onboard new credentials.

**Not a production vault:** the local encrypted credential workflow does not provide managed key storage, a key-rotation lifecycle, or production secret access auditing. Current role and tenant authorization does not turn the local key file into a managed secret service. For renewable workload modes and their operator prerequisites, see [provider-workload-onboarding.md](provider-workload-onboarding.md). Production deployments require managed identity and a dedicated secrets service. Continue to bind local password mode to `127.0.0.1`.
