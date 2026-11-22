# Security policy

## Supported code

Security fixes are developed against the latest commit on `main`. Older commits
and locally modified builds are not maintained as separate supported releases.

## Reporting a vulnerability

Do not publish credentials, exploit details, or sensitive repository data in a
public issue. Use GitHub's private vulnerability reporting / security advisory
flow for this repository when available. If that feature is not enabled, contact
the repository owner privately through GitHub before disclosing details.

## Security model and operator responsibilities

SL-AstraCore is a local-first, single-user repository analysis tool. It is not
a multi-tenant service and does not provide user accounts or role-based access
control.

- Direct dashboard launches bind to `127.0.0.1` by default. Setting
  `ASTRA_HOST` explicitly opts into a different bind address.
- The Docker image binds inside the container to `0.0.0.0` so port publishing
  works. Do not publish it directly to an untrusted network. Put it behind a
  TLS-terminating reverse proxy and firewall.
- Dashboard API routes require the bearer token. Keep the terminal output and
  `ASTRA_TOKEN` private. Do not put the token in URLs or shared logs.
- Provider API keys are stored server-side in
  `$ASTRA_HOME/providers.json` (default: `~/.astra/providers.json`). On POSIX
  systems the file is written with mode `0600`. The key is **not encrypted at
  rest**; on Windows, protect the data directory with the account's filesystem
  ACLs. Do not commit this file, copy it into support bundles, or share the
  `.astra` directory.
- Remote provider endpoints must use HTTPS. Plain HTTP is accepted only for
  loopback endpoints such as local Ollama. Only configure endpoints you trust:
  the API key is sent to the configured endpoint.
- Repository source and documentation are untrusted input. A model may follow
  malicious instructions embedded in a repository. Review proposed edits and
  their diffs; never execute generated code just because the model proposed it.
- AI review does not write source files. Applying a reviewed proposal is a
  separate explicit operation. Protect the repository and its database files
  with normal operating-system permissions.

## Known limitations

The dashboard has one bearer-token boundary, not per-user identities or RBAC.
The application does not terminate TLS itself. Provider credentials are
permission-restricted but plaintext at rest. These limitations are documented
rather than represented as stronger protections than they are.
