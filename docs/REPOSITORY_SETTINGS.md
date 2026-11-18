# GAMe Community — GitHub Settings to Verify

Repository: https://github.com/Happili-platform/game
Visibility verified PUBLIC on 2026-11-16. These settings are GitHub-side
administrative controls and cannot be enforced merely by committing a file.

## main and develop
- Enforce a PR before merging; require successful `build` and `dco` checks.
- Require resolution of review conversations.
- Block branch deletion and force pushes.
- Configure reviewer approval after a second eligible reviewer is available.
- CODEOWNERS is not sufficient without branch review enforcement.
- Test effective enforcement; no unreviewed direct pushes should succeed.

## Repository and organization security
- Enable secret scanning and push protection wherever available.
- Enable Dependabot alerts and dependency security updates.
- Enable private vulnerability reporting and a private maintainer contact.
- Limit Actions token permissions to least privilege; restrict untrusted Actions.
- Review maintainers, teams and bypass permissions periodically.
- Require sign-off on new community commits (`git commit -s`).

## Verification record
Record the date, administrator and screenshot or export of each enabled rule.
Do not mark any GitHub-side control verified merely because a workflow file
or this document exists.
