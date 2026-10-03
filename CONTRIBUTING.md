# Contributing to SyncFlow

Thanks for helping improve SyncFlow!

## Development Setup

```bash
git clone <repo-url>
cd syncflow

# Backend
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd ..

# Frontend
npm install

# Run in dev mode (hot reload)
./start-dev.sh                  # Windows: start-windows.bat
```

Requirements: Node 20+, Python 3.11+.

## Before Opening a PR

```bash
npx tsc --noEmit          # typecheck (must be clean)
backend/tests/run_all.sh  # security suite — 134 checks, ~5 min, must be green
```

## Guidelines

- **Security first**: this app moves files between devices on your network.
  Any networking/crypto change must keep (or extend) the test suite green.
- **Honest documentation**: never claim features that don't exist (TLS, WAN
  relay, etc. are explicitly *not* claimed — see README "Honest scope").
- **No secrets, no telemetry**: never commit keys, tokens, device identities,
  or add phone-home code.
- Match the existing code style; keep diffs focused on one concern.
- Update `SECURITY_REPORT.md` if you change the threat model or hardening.

## Where to Start

- Good first issues: labeled `good first issue`
- Bugs: `bug` label · Features: `enhancement` label

## Code of Conduct

Be respectful and constructive. Harassment or bad-faith contributions are not
tolerated.
