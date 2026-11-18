# GAMe Community — Public Alpha Governance Checklist

**Audit date:** 2026-11-16. Repository is already PUBLIC. This checklist is a
living evidence register, not a legal opinion or production certification.

## Confirmed in public repository
- [x] Original author's stated identity and publisher explicitly documented in COPYRIGHT.
- [x] Complete AGPLv3 LICENSE and contribution licensing policy present.
- [x] Community edition has a fresh Git root commit (do not import old repository history).
- [x] Current main tree has no tracked SQLite database or key files in the audited tree listing.
- [x] GitHub Actions Python tests and PR-targeted DCO workflow exist (verify runs after merge).
- [x] First-party source and UI include AGPL SPDX notices; check all future additions.
- [x] Documentation and login/password UI link to community source.
- [x] Docker/Compose configuration defaults to password mode and localhost host port binding.

## Open verification / external action required
- [ ] Keep a private, dated original-author rights and publisher authorization record; review employment, consultancy, invention-assignment and third-party constraints with counsel as needed.
- [ ] Complete dependency/license, browser asset, base-image and vendored-content attribution inventory for a reproducible release; see THIRD_PARTY_LICENSE_AUDIT.md.
- [ ] Run and archive full reachable-history Gitleaks scan, including all remote refs. Verify PR/cached old repository objects separately if relevant.
- [ ] Confirm no previously exposed actual secrets require rotation; if there were, rotate immediately.
- [ ] Confirm DCO check and Python tests are green for the hardening PR and require both on protected main and develop.
- [ ] Verify enforced GitHub branch rules, PR reviews, force-push/deletion restrictions, secret scanning, push protection, Dependabot and private vulnerability reporting in Settings.
- [ ] Test a fresh clone, first-run account setup, localhost login and Docker Compose bootstrap.
- [ ] Validate the user-visible corresponding-source links in a running distribution.
- [ ] Publish a versioned alpha release and its documented limitations when ready.

**Caution:** No contributor DCO or GitHub CODEOWNERS file is an ownership
assignment. AGPLv3 permits third-party forks and commercial use subject to its
terms. Pending legal and security checks must not be described as completed.
