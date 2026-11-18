# GAMe Security Policy

## Alpha status

GAMe v0.3.5 is an alpha development baseline, not certified for
production use. Do not assume controls, isolation, authentication,
authorization, logging, or data handling are sufficient for sensitive
enterprise workloads without independent validation.

## Supported versions

Security fixes are evaluated against the current actively maintained branch.
Old alpha builds and prototypes are not guaranteed ongoing support.

## Reporting a vulnerability

**Do not disclose vulnerabilities, exploits, credentials, tokens, or sensitive
customer details in public issues, discussions, or pull requests.**

Use GitHub's **Report a vulnerability** feature under the repository
**Security** tab if private vulnerability reporting is enabled. If it is not
enabled, do not post vulnerability details publicly. Contact the maintainers
through an approved private channel listed in the organization's profile
after one is established.

Maintainers should enable GitHub private vulnerability reporting before
making the repository public.

Include a description, affected version or commit, impact, safe reproduction
steps, and proposed mitigation when possible. Never include working secrets
or real enterprise data.

## Disclosure and remediation

Maintainers will evaluate reports, coordinate reasonable remediation, and
publish an advisory where warranted. No fixed SLA is promised during alpha.

## Production deployment notice

Before deployment, independently assess least-privilege credentials, tenant
isolation, network access, authentication, backups, dependency provenance,
runtime audit coverage, and data retention.
