# Security Policy

This server handles some of the most sensitive data in an enterprise (HR,
compensation, national identifiers). Security reports are taken seriously.

## Reporting a vulnerability

- **Email:** mohantyajitesh@gmail.com with subject line `[SECURITY] fusion-hcm-mcp-server`
- Or use GitHub's **private vulnerability reporting** on this repository
  (Security tab → Report a vulnerability), if enabled.

Please include: affected version/commit, a description, reproduction steps or
a proof of concept, and impact as you assess it.

**Please do not open public issues for suspected vulnerabilities.**

## What to expect

- Acknowledgment within **72 hours**.
- An assessment and remediation plan within **14 days** for confirmed issues.
- Credit in the release notes if you want it (tell us how to attribute you).

## Scope notes

- The server's authorization ceiling is the configured Oracle integration
  user's RBAC. Reports of the form "the integration user can do X" where X is
  within that user's granted roles are configuration issues, not
  vulnerabilities — but redaction/audit bypasses, credential leaks, gate
  bypasses (writes/dry-run/schema validation), and SSRF are firmly in scope.
- Supported version: the latest release on `main`.

## Supported versions

| Version | Supported |
|---|---|
| latest `main` / newest release | ✅ |
| older tags | ❌ |
