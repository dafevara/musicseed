# CLI Reference

This page is generated from the `musicseed-cli` Typer app
(`musicseed_cli.app:app`), using the same docstrings that power
`musicseed-cli --help`.

`musicseed` starts the API/web product; `musicseed-cli` is the separate command-line surface.
From a checkout, use `uv run --project cli musicseed-cli ...` after syncing the CLI environment.
Global options such as `--config` and `--log-level` go before the command name.

`recommend` is read-only and has no `--dry-run` flag. `playlist` previews and confirms before
creating a Plex playlist; `populate --dry-run` previews an existing playlist, and `populate`
confirms before appending the displayed IDs. `import` is incremental by default (`--full`
re-imports); it has no `--limit` or `--dry-run` option. `import-plex-sonic` is a separate local
vector import, needed after Plex analyzes new tracks.

```bash
uv run --project cli musicseed-cli recommend --seed-id 123 --limit 20 --explain
```

Use a real local track ID in place of `123`. See [local runtime](infra/local-runtime.md) for
configuration and [recommendation resolvers](resolvers/recommendation-resolvers.md) for scoring.

::: mkdocs-typer2
    :module: musicseed_cli.app
