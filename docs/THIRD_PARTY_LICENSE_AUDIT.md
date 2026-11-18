# Third-party dependency license audit — GAMe v0.3.5

This is a **repeatable review procedure**, not a certification of legal compliance. The source code is offered under `AGPL-3.0-only`; third-party dependencies retain their own copyrights and license terms.

## Reproduce the Python inventory

From a fresh Python 3.13 virtual environment in the repository root:

```sh
python -m pip install -r requirements-dev.txt -r requirements-connectors.txt
python -m pip install pip-licenses
python -m piplicenses --format=markdown --with-urls --output-file=dependency-licenses.md
```

Save the resulting report outside the Git checkout (for example, `~/game-security-audit/`). Review the exact versions shipped or deployed. This inventory also includes tools and transitive dependencies in the active environment; it is not a locked software bill of materials or proof of what is bundled in a release.

## Initial Python license review (local environment, November 2026)

Reported license families: MIT/MIT-0, BSD-2/3, Apache-2.0, Apache-2.0 OR BSD-3, MPL-2.0, and PSF-2.0. No obvious AGPLv3 incompatibility was identified **from the reported metadata alone**.

Points requiring distribution-specific confirmation:

- `certifi`: reported MPL-2.0. Retain its notices; comply with any applicable MPL source-availability obligations for covered files and modifications.
- `cryptography`: reported dual licensing (Apache-2.0 OR BSD-3-Clause); preserve applicable license notices.
- `typing_extensions`: reported PSF-2.0; confirm its applicable license text/notices.
- `google-auth`, `requests`, and `python-dateutil`: tools may emit descriptive names rather than SPDX identifiers; validate against upstream license files.
- Review bundled, copied, generated, or vendored JavaScript/CSS/fonts and container base images separately. A Python package inventory does **not** cover them.

## Release gate

1. Capture dependency versions and licenses for the **actual** release environment.
2. Verify license metadata against authoritative license files; review new dependencies and nonstandard licenses manually.
3. Check required attribution, copyright notices, complete license texts, and any source-offer requirements in distributable artifacts.
4. Inventory client-side libraries/assets, containers, and optional integrations separately.
5. Record reviewer, date, exceptions and remediation in the release checklist.
6. Obtain legal review of copyright ownership and any unresolved license obligations before changing repository visibility.

Related: [Public alpha publishing checklist](PUBLISHING_CHECKLIST.md), [Copyright notice](../COPYRIGHT), [AGPLv3 license](../LICENSE).
