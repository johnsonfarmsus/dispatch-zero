# Contributing to Dispatch Zero

Thanks for your interest. This project is maintained as a hobby — that shapes a few expectations on both sides.

## Bug reports

Genuinely welcome. Open an issue with:
- What you did
- What you expected
- What actually happened
- Browser / OS / approximate location accuracy if it's a geo-related bug

If you can paste a relevant snippet of the server log (`docker compose logs app`), that helps a lot.

## Pull requests

PRs welcome — with a couple of caveats:

- **For anything substantive (new feature, architectural change, new external dependency), open an issue or draft PR first.** Saves both of us from you doing work that doesn't land.
- **Keep the test suite green.** `pytest` should pass before you push. If you're adding behavior, add a test.
- **Match the existing style.** No formatter is enforced, but the code leans toward boring/explicit over clever.
- **No SLA on review.** I might get to it in a day, I might get to it in a month. If you need it merged faster than that, you're better off running a fork.

Pure documentation/typo PRs are fast-pathed.

## What's in scope

In rough order of "yes please" → "probably not":

- **Yes please:** rural-area data sources (HIFLD, Overture Maps, state-specific GIS layers), new GNIS importer feature classes, additional handler personas (with prompts + voice samples), accessibility improvements, mobile UX polish, test coverage gaps.
- **Probably yes, with discussion:** new discovery tiers, additional auth methods (passkeys), federation between instances.
- **Probably not:** anything that requires non-AGPL dependencies, anything that adds tracking/analytics, anything that breaks the "no email, no PII" data model.

## Development setup

See [README.md → Self-hosting → Local dev](README.md#local-dev).

The repository uses Alembic for migrations. If you change a model:

```bash
docker compose exec app alembic revision --autogenerate -m "your change"
# review the generated migration file before committing
docker compose exec app alembic upgrade head
```

## Running tests

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest
```

Subset:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/test_import_gnis.py -v
```

## Branching and commits

- Branch off `main`
- Conventional commit prefixes appreciated but not required (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`)
- Squash on merge is the default

## Code of conduct

Be decent. Disagree about technical choices, not about people. Concrete behavior is covered by the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) — that's the baseline expectation here, even though we don't ship a separate file for it.
