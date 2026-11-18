# Adding SPDX Notices to GAMe Source

The project uses `AGPL-3.0-only` for first-party code, subject to verification
of copyright ownership and exclusions for third-party material.

Examples for **original first-party** files:

Python:
```python
# SPDX-License-Identifier: AGPL-3.0-only
```

JavaScript, CSS:
```javascript
// SPDX-License-Identifier: AGPL-3.0-only
```

HTML:
```html
<!-- SPDX-License-Identifier: AGPL-3.0-only -->
```

Shell (after an existing shebang):
```bash
# SPDX-License-Identifier: AGPL-3.0-only
```

Where a verified copyright holder exists, also include an accurate copyright
line, such as `# SPDX-FileCopyrightText: 2026 <verified rights holder>`.

**Do not blindly add these notices to vendored code, bundled libraries,
generated files, existing third-party assets, or files whose copyright
ownership has not been established.** Preserve existing third-party notices
and SPDX identifiers.

Source-file edits must be performed against the actual v0.3.5 code after it
is imported. This documentation does not imply application source has already
been annotated.
