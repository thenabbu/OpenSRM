# Contributing to OpenSRM

Thanks for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork
3. Create a feature branch (`git checkout -b feature/my-feature`)
4. Make your changes
5. Test locally: `docker compose up -d --build`
6. Commit with a clear message
7. Push to your fork and open a Pull Request

## Development Setup

```bash
docker compose up -d --build
```

The app will be available at `http://localhost:8083`.

## Guidelines

- Keep it simple — if stdlib does it, use stdlib
- No unnecessary dependencies
- Test your changes end-to-end before submitting
- Use meaningful commit messages

## Reporting Issues

Open an issue with:
- What you expected
- What actually happened
- Steps to reproduce
- Your environment (OS, Docker version)

## Security

If you find a security vulnerability, please open a private issue or contact the maintainer directly. Do not open a public issue for security vulnerabilities.
