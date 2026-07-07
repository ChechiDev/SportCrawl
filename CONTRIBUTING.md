# Contributing

## Setup

```bash
uv sync
git config core.hooksPath .github/hooks
chmod +x .github/hooks/commit-msg
```

## Commit format

This project uses [Conventional Commits](https://www.conventionalcommits.org/).

```
<type>(<scope>): <description>

Types: feat, fix, test, refactor, chore, ci, docs, perf
Scope: optional — e.g. core, persistence, country, cli
```

Examples:
```
feat(core): add BaseRepository with default async CRUD
test(core): add unit tests for exception hierarchy
fix(persistence): correct Alembic async env.py runner
chore: add commitizen and CI workflow
ci: add release workflow for SemVer tags
```

Enforced locally via `commit-msg` hook (commitizen). CI does not re-check commit format.

## Versioning

SemVer via commitizen (`cz bump`):
- `feat:` → MINOR bump (0.x.0)
- `fix:` / `refactor:` / `perf:` → PATCH bump (0.0.x)
- `feat!:` or `BREAKING CHANGE:` footer → MAJOR bump

Bump and tag before opening a PR to main:
```bash
uv run cz bump          # bumps version + creates tag
git push origin --tags  # triggers the release workflow
```

## Branch naming

```
feat/<short-description>
fix/<short-description>
chore/<short-description>
refactor/<short-description>
ci/<short-description>
```

## CI requirements

All four jobs must be green before merging:
- **lint**: ruff + flake8
- **typecheck**: mypy --strict
- **test**: pytest ≥80% coverage
- **security**: pip-audit
