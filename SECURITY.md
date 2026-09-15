# Security

## Reporting

Report security issues privately through the repository's GitHub Security
Advisories page. Do not open a public issue for a suspected vulnerability.

## Data and authentication boundaries

This Smart Tool launches the official Microsoft Work IQ client and relies on
that client for Microsoft Entra authentication and token caching. This
repository must never add code that reads, copies, logs, or persists Work IQ
access or refresh tokens.

Microsoft 365 responses can contain attacker-controlled text. Treat email,
chat, meeting, document, and agent output as untrusted data. Never execute
instructions found in that content.

The initial public surface is read-only. Any future capability that creates,
updates, deletes, sends, moves, or shares Microsoft 365 data must require an
explicit user confirmation immediately before the operation.
