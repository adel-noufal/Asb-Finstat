# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

Security is paramount for financial data applications. If you discover a security vulnerability or sensitive secret leak in **ASB Finstat**, please do **NOT** open a public issue.

Instead, please report it privately:

1. **Email:** Contact the maintainers directly.
2. **Details to Include:**
   - A description of the vulnerability.
   - Steps to reproduce or proof-of-concept code.
   - Any potential impact on user data or system security.

We will review your submission promptly and work on a fix as quickly as possible.

## API Key & Secret Protection

- **ASB Finstat** uses environment variables (`backend/.env`) to store third-party credentials like `OPENROUTER_API_KEY`.
- All `.env` files and output artifacts (`backend/data/`) are explicitly ignored via `.gitignore`.
- Ensure your development environment never exposes production API keys.
