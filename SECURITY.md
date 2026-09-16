# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue**
2. Email the maintainer directly, or
3. Open a private security advisory on GitHub

## What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Response

You can expect:
- Acknowledgement within 48 hours
- Assessment within 1 week
- Fix or mitigation within 2 weeks (depending on severity)

## Scope

- This software scrapes the SRM student portal using Playwright
- It stores credentials (Fernet-encrypted) in SQLite
- It serves a web dashboard with session cookies

## Out of Scope

- Issues with the SRM student portal itself
- Social engineering attacks
- Physical attacks
