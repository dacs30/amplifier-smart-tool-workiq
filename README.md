# Amplifier Smart Tool for Work IQ

A library-first Smart Tool that packages safe, repeatable Microsoft 365
workflows over the official [Microsoft Work IQ](https://github.com/microsoft/work-iq)
MCP server.

The tool uses the Microsoft 365 account authenticated by the official Work IQ
client. It does not request, inspect, store, or print access tokens.

> **Status:** Initial production-oriented implementation. Work IQ is currently
> in public preview, so its APIs and client behavior may change.

## Capabilities

| Capability | Kind | Description |
|---|---|---|
| `doctor` | Deterministic | Check local prerequisites without authenticating. |
| `manifest` | Deterministic | Return the canonical Smart Tool manifest. |
| `accept-eula` | Setup | Explicitly accept Microsoft's Work IQ EULA. |
| `authenticate` | Setup | Start the official Work IQ interactive sign-in flow. |
| `agents` | Model-backed | List Microsoft 365 Copilot agents available to the user. |
| `ask` | Model-backed | Ask Work IQ a read-only workplace question. |
| `fetch` | Model-backed | Fetch an explicitly allowed Microsoft 365 resource path. |
| `daily-briefing` | Model-backed | Build a prioritized daily work briefing. |
| `meeting-prep` | Model-backed | Prepare context for a specific meeting. |
| `workflow` | Mixed | Create and run reusable domain-specific workflows. |

No create, update, delete, or action capability is exposed. Work IQ tenant
policy also blocks mutation operations by default.

## Prerequisites

- Python 3.11 or later
- Node.js 18 or later, including `npx`
- Microsoft 365 tenant access enabled for Work IQ
- Admin consent for the Work IQ application

The first authentication is interactive:

```powershell
uv run --no-project src\amplifier_smart_tool_workiq\cli.py accept-eula --yes

uv run --no-project src\amplifier_smart_tool_workiq\cli.py authenticate
```

Review the EULA at <https://github.com/microsoft/work-iq> before accepting it.
The Smart Tool never accepts legal terms implicitly.

Work IQ sets the selected account as its persisted default. You can select a
cached account explicitly:

```powershell
uv run --no-project src\amplifier_smart_tool_workiq\cli.py `
  --account user@contoso.com daily-briefing
```

## Examples

```powershell
uv run --no-project src\amplifier_smart_tool_workiq\cli.py doctor
```

```powershell
uv run --no-project src\amplifier_smart_tool_workiq\cli.py daily-briefing `
  --date 2026-09-15 `
  --time-zone America\New_York
```

```powershell
uv run --no-project src\amplifier_smart_tool_workiq\cli.py meeting-prep `
  --meeting "Architecture review" `
  --date 2026-09-16
```

```powershell
uv run --no-project src\amplifier_smart_tool_workiq\cli.py fetch `
  --path "/me/messages?`$select=id,subject,from,receivedDateTime,isRead&`$top=10"
```

Every command emits exactly one JSON document to stdout. Diagnostics are
written to stderr.

## Domain-specific workflows

Workflow profiles let users package repeatable Work IQ expertise without
writing Python. A profile is a versioned JSON prompt template with declared
inputs:

```json
{
  "format": 1,
  "name": "project-status",
  "description": "Summarize current project status and risks.",
  "inputs": ["project", "review_date"],
  "prompt": "Prepare a status review for {project} as of {review_date}."
}
```

Validate and persist it:

```powershell
workiq-smart-tool workflow validate --file .\project-status.json
workiq-smart-tool workflow create `
  --file .\project-status.json `
  --confirmed
```

Run it from any directory:

```powershell
workiq-smart-tool workflow run `
  --name project-status `
  --input project="Project Alpha" `
  --input review_date=2026-09-15
```

Profiles are stored in the user's configuration directory, separate from the
installed package. Creating, replacing, or deleting a profile requires explicit
confirmation. See [`examples`](examples/) for starting profiles.

## Copilot CLI

Install the executable globally from the public Git repository; no clone is
required:

```powershell
uv tool install `
  "git+https://github.com/dacs30/amplifier-smart-tool-workiq.git"
```

If dependency resolution fails because of network or certificate policy,
configure uv to use your organization's approved Python package index or
certificate settings, then retry. Do not publish organization-specific package
feed URLs or credentials in issues or logs.

Install the shared Smart Tools catalog skill globally:

```powershell
npx skills add microsoft/amplifier-smart-tools-catalog `
  --skill amplifier-smart-tools-catalog `
  --agent github-copilot `
  --global
```

Restart Copilot CLI, or run `/skills reload` in an existing session. Verify the
global installation with:

```powershell
workiq-smart-tool doctor --local-only
copilot skill list
```

For development from a local checkout, add `--editable` and replace the Git URL
with the checkout path.

```text
Find and use a Smart Tool to prepare my Microsoft 365 daily briefing.
```

```text
Find and use a Smart Tool to prepare me for tomorrow's architecture review.
```

The shared catalog skill selects the Work IQ Smart Tool and reads its installed
CLI help before invocation. The Smart Tool, not the calling agent, owns the Work
IQ workflow.

## Authentication behavior

The tool delegates authentication to the official `@microsoft/workiq` client:

1. `authenticate` runs `workiq auth login`.
2. Work IQ opens the Microsoft Entra sign-in experience when needed.
3. Work IQ persists the selected default account and cached authentication.
4. Later MCP sessions reuse that account silently when policy permits.

Reauthentication can still be required after logout, token revocation, account
or tenant changes, Conditional Access challenges, or cache removal.

## Security model

- Microsoft 365 data is treated as untrusted input.
- Only read-oriented Work IQ tools are exposed by the public library API.
- Resource paths must be relative and begin with `/me/`, `/users/`, or
  `/sites/`.
- Collection fetches must specify `$select`; callers should also specify
  bounded `$top` values.
- Authentication output is sanitized before errors are returned.
- Policy denials are surfaced and are never retried as transient failures.
- Access tokens and authorization headers are redacted from diagnostics.

See [SECURITY.md](SECURITY.md) for reporting instructions and operational
guidance.

## Development

```powershell
python -m unittest discover -s tests -v
```

Validate the distribution with the Smart Tools conformance kit:

```powershell
uv run path\to\amplifier-smart-tools\conformance\run.py .
```
