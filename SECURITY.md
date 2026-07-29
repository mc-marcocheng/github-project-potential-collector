# Security Policy

## Collector security

Repository content is untrusted input.

The collector:

- Never executes downloaded repository files.
- Never renders README HTML.
- Never follows links found in repository content.
- Never interpolates repository content into shell commands.
- Limits downloaded README size.
- Stores sampled identities only in a private data repository.
- Avoids printing repository names or README content in public logs.

## GitHub Actions

The production collector runs only through scheduled or manual workflows.

Do not:

- Run the collector from `pull_request_target`.
- Expose data-repository credentials to pull requests.
- attach a self-hosted runner to this public repository.
- grant the public repository token write permissions.
- print secrets or authenticated remote URLs.

The private data token should be a fine-grained token or GitHub App credential
restricted to the private data repository.

Protect `.github/workflows/**` with CODEOWNERS and required review.

## Reporting vulnerabilities

Report security issues privately to the repository owner rather than opening a
public issue containing credentials, sampled identities, or private data.
