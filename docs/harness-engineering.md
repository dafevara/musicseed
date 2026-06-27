# Harness Engineering For MusicSeed

This repo uses a lightweight agentic harness inspired by OpenAI's harness engineering article and
Martin Fowler's harness engineering framing. The goal is not to maximize automation for its own
sake. The goal is to make future agent work cheaper, safer, and better aligned with this personal
project.

## Local Interpretation

MusicSeed does not need enterprise-scale CI, custom architecture linters, an observability stack,
or autonomous merge workflows. It does benefit from:

- A short provider-neutral `AGENTS.md` as the starting map.
- Focused docs in `docs/` as the system of record.
- Cheap verification commands agents can run without touching real library state.
- Clear safety boundaries around Plex, local databases, credentials, and long-running jobs.
- Explainable recommendation behavior so agents and humans can inspect outcomes.
- Occasional doc cleanup when code and docs drift.

## Guides

Guides are feedforward context that shape agent behavior before work starts.

- `AGENTS.md`: root map, safety rules, command checklist, docs routing.
- `README.md`: human entry point and normal local usage.
- `docs/product/overview.md`: product scope and non-goals.
- `docs/domain/music-recommendation.md`: recommendation concepts and signal semantics.
- `docs/infra/local-runtime.md`: local services, config, logs, commands, operational safety.
- `docs/resolvers/recommendation-resolvers.md`: seed resolution, candidate pools, scoring,
  diversity, and explainability.

Keep guides short and linked. If a doc grows into many unrelated topics, split it.

## Sensors

Sensors are feedback mechanisms that tell an agent whether work is valid.

Computational sensors:

```bash
python3 -m compileall -q src/musicseed
uv run ruff check src
uv run musicseed --help
```

Runtime sensors:

```bash
uv run musicseed status
uv run musicseed recommend --seed-id 123 --limit 20 --dry-run --explain
```

Human sensors:

- Inspect a dry-run playlist before writing to Plex.
- Review `logs/latest.log` after failed imports, enrichment runs, or embedding jobs.
- Prefer a small sample run before full-library work.

## Fit-For-Project Practices

Do:

- Add docs when knowledge would otherwise live only in chat or memory.
- Add tests for pure matching, scoring, filtering, and normalization behavior.
- Keep long-running jobs resumable.
- Make command failures actionable.
- Promote repeated review feedback into docs or code checks.

Avoid:

- Large monolithic instruction files.
- Complex CI or custom linting before there is repeated pain.
- New services for problems a local command or log file can solve.
- Background automation that touches Plex or the full library without user intent.
- Treating recommendation outputs as objectively correct without human listening checks.

## Maintenance Loop

When an agent struggles, improve the harness in the smallest useful way:

1. Was the missing context already in the repo? Add or fix a link from `AGENTS.md` or a topic doc.
2. Was the rule important and repeated? Add a test, lint, or explicit command.
3. Was the command risky or slow? Add a safer limited example.
4. Did code behavior change? Update the focused doc in the same change.

For this repository, a monthly or after-major-change doc pass is enough. Search for stale commands,
renamed modules, and docs that describe intended behavior differently from the code.
