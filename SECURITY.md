# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities through GitHub's private vulnerability
reporting: go to the **Security** tab of this repository and choose **Report a
vulnerability**.

Please do not open a public issue for a security vulnerability.

We aim to acknowledge a report within 72 hours and to keep you updated as we
work on a fix. If you would like credit in the release notes, say so in your
report.

## Supported Versions

Alethic is pre-1.0. Only the latest release receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Scope and Known Limitations

Alethic is a governance layer, so it is worth being precise about what it does
and does not currently defend against. The following are **known** and are not
useful as vulnerability reports — though better ideas for fixing them are very
welcome, as issues or pull requests.

### The HTTP API is unauthenticated

The FastAPI service under `src/alethic_kernel/api/` is a development and evaluation tool.
It has no authentication or authorization, every caller shares one kernel, and
`role` is read from the request body — so a client can claim the `kernel` role
and commit without validation. `trace_id` namespaces state but does not isolate
it. Request bodies are unbounded and records are never evicted.

Do not expose it to untrusted traffic. See
[docs/http-api.md](docs/http-api.md#security).

### The permissions matrix is worker discipline, not a security boundary

In-process, the role is declared by the caller. The matrix keeps a well-behaved
worker in its lane; it does not defend against code that lies about its role.
Only give kernel access to code you trust.

### The library's threat model

The library assumes a **trusted integrator** and an **untrusted model**. That
second half is the part Alethic is built to handle: planner output is validated
before commitment, and the agent rebuilds action payloads from tool data rather
than trusting model-supplied fields, so prompt injection should not be able to
push an unvalidated action through the kernel.

**A way to defeat that is exactly what we want to hear about.** If you can make
the kernel commit a belief, action, or prediction that its validation pipeline
should have rejected — through model output, evidence handling, TTL or
confidence edge cases, or constraint evaluation — please report it. That is the
core guarantee, and a bypass is a real vulnerability regardless of how contrived
the setup looks.
