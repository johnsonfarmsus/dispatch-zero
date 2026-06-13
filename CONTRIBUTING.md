# Contributing to Dispatch Zero

Thanks for your interest. This project is maintained as a hobby, which shapes a few expectations on both sides.

## Bug reports

Genuinely welcome. Open an issue with:
- What you did
- What you expected
- What actually happened
- Browser / OS / approximate location accuracy if it's a geo-related bug

If you can paste a relevant snippet of the server log (`docker compose logs app`), that helps a lot.

## Pull requests

PRs welcome, with a couple of caveats:

- **For anything substantive (new feature, architectural change, new external dependency), open an issue or draft PR first.** Saves both of us from you doing work that doesn't land.
- **Keep the test suite green.** `pytest` should pass before you push. If you're adding behavior, add a test.
- **Match the existing style.** No formatter is enforced, but the code leans toward boring/explicit over clever.
- **No SLA on review.** I might get to it in a day, I might get to it in a month. If you need it merged faster than that, you're better off running a fork.

Pure documentation/typo PRs are fast-pathed.

## What's in scope

In rough order of "yes please" → "probably not":

- **Yes please:** OSM round-trip improvements (better category-to-tag mapping, Wikidata enrichment on wp-sourced publishes, additional ambiguous-category subtype pickers), additional handler personas (with prompts + voice samples), accessibility improvements, mobile UX polish, test coverage gaps.
- **Probably yes, with discussion:** new discovery tiers, additional auth methods (passkeys), federation between instances, rural-area data sources (HIFLD, Overture Maps, state-specific GIS layers) and new GNIS importer feature classes as fallbacks for areas where OSM coverage is thin.
- **Probably not:** anything that requires non-AGPL dependencies, anything that adds tracking/analytics, anything that breaks the "no email, no PII" data model, anything that publishes to OSM without explicit per-edit reviewer approval.

## Development setup

See [README.md → Self-hosting → Local dev](README.md#local-dev).

After cloning, install the repo's git hooks once:

```bash
git config core.hooksPath .githooks
```

The pre-commit hook blocks commits to `deploy/*.sh` that would re-introduce
the data-loss bug from 2026-06-02 (rsync `--delete` without `--exclude 'uploads'`
silently wiped captured user photos on the VPS).

The repository uses Alembic for migrations. If you change a model:

```bash
docker compose exec app alembic revision --autogenerate -m "your change"
# review the generated migration file before committing
docker compose exec app alembic upgrade head
```

## Running tests

Backend (pytest, in the test container):

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest
```

Subset:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/test_import_gnis.py -v
```

Frontend (Node's built-in test runner, no dependencies to install — needs
Node 21+). The harness uses a tiny headless DOM stub (`frontend/test-setup.mjs`)
so the real modules run without a browser:

```bash
cd frontend && npm test
```

It covers the highest-value untested layer: the router (matching, error
boundary, cleanup hooks), the GPS/flow helpers (geo math, fix/error
listeners), the `el()` DOM builder, and the api.js fetch wrapper (including
NetworkError normalization).

## Branching and commits

- Branch off `main`
- Conventional commit prefixes appreciated but not required (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`)
- Squash on merge is the default

## Code of conduct

Be decent. Disagree about technical choices, not about people. Concrete behavior is covered by the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). That is the baseline expectation here, even though we don't ship a separate file for it.
