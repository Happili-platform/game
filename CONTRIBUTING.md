# Contributing to GAMe

Thank you for contributing to GAMe, an open-source project published
by Happili Platform.

## License and contributor rights

The project is distributed under `AGPL-3.0-only`. Unless a file explicitly
provides a different compatible license, contributions must be licensed under
`AGPL-3.0-only`.

You retain ownership of your contribution. By submitting it, you confirm that
you have the necessary rights to submit it under the project's license.
Your contribution does **not** automatically transfer copyright or grant
Happili Platform proprietary relicensing rights.

## Developer Certificate of Origin (DCO)

Each commit must include a DCO sign-off. Use:

```bash
git commit -s -m "Describe your change"
```

This adds a `Signed-off-by: Name <email>` trailer. The sign-off certifies
the [Developer Certificate of Origin v1.1](https://developercertificate.org/).
It is not the same as a Contributor License Agreement (CLA).

## Workflow

1. Open an issue to discuss significant features, integrations, or behavior changes.
2. Create a feature branch from the latest develop branch.
3. Make focused changes and include relevant tests and documentation.
4. Use SPDX license identifiers on original first-party source files.
5. Run applicable tests, linters, security checks and secret scans.
6. Open a pull request that describes impact, risks, and test results.
7. Address code review comments; maintainers decide whether to merge.

## Upstream contributions and forks

Commercial use and forks are welcome within AGPLv3's terms. Where the license
requires covered source to be offered to recipients or network users, that
does not require a pull request to this repository.

We encourage businesses and community members to submit general-purpose
improvements upstream so everyone benefits. Maintainers may review separately
published AGPL-compliant improvements for possible incorporation.

## Security and third-party materials

Do not submit secrets, customer data, proprietary code without authorization,
or components whose licenses conflict with this project. Preserve original
attributions. Follow [SECURITY.md](SECURITY.md) for vulnerability reports.

## Maintainer review

Maintainers reserve the right to request changes or decline contributions
based on security, architecture, test quality, scope, and project priorities.


### DCO checks on pull requests

The `DCO Sign-off / dco` GitHub check validates sign-off trailers on every
commit in a new pull request; a sign-off is an attestation, not a copyright
assignment. If a commit lacks a sign-off, use `git commit --amend -s` for the
last commit you authored, or carefully rebase/sign off your own earlier commits
on your feature branch. Do not rewrite shared or protected history. Check the
commit author email and the sign-off email match.
