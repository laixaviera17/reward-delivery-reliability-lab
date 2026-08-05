# Security Policy

## Supported version

Security fixes are applied to the latest revision on `main`.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature instead of opening
a public issue. Include reproduction steps, affected endpoints, impact, and a
suggested mitigation when available.

Do not include production credentials, personal data, or access tokens in a
report. The credentials in `.env.example` are local-development defaults only.

## Scope and current limitations

This repository is a portfolio/reference implementation. It does not yet
provide authentication, authorization, rate limiting, secret management, or
tenant isolation and must not be exposed to an untrusted network as-is.
