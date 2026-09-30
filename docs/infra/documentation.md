# Building and Maintaining the Documentation

Edit Markdown and HTML under `docs/` and navigation in `mkdocs.yml`. `site/` is generated,
ignored by Git, and replaced by a build; do not edit its pages directly. It is separate from
`web/out/`, the Next.js product UI served by `musicseed`.

From the repository root, create a local environment once:

```bash
uv venv --python 3.12 .venv-docs
uv pip install --python .venv-docs -r docs/requirements-docs.txt
```

Python 3.12 or newer is supported. Virtual environments are machine-specific: after moving a
checkout between machines or operating systems, recreate `.venv-docs` rather than copying it.

Build or preview from the repository root:

```bash
.venv-docs/bin/mkdocs build --strict
.venv-docs/bin/mkdocs serve
```

The build writes `site/`; the preview server defaults to `http://127.0.0.1:8000`.

## Sources of truth

| Reference | Source |
|---|---|
| CLI commands, options, defaults | `musicseed_cli.app:app`, imported by mkdocs-typer2 |
| Core and API Python references | Current source files read by mkdocstrings |
| MCP tool signatures and descriptions | `mcp/src/musicseed_mcp/server.py`, statically read by mkdocstrings |
| HTTP request contract | FastAPI routes and their live OpenAPI schema; see [HTTP API](../api-reference/http-api.md) |
| Workflows and operational behavior | Handwritten guides checked against services, adapters, and tests |

The docs environment installs core, API, and CLI in editable mode. MCP is read from `mcp/src`
without importing or starting its server, so building docs does not require the MCP runtime.
No build step should connect to Plex, run enrichment, or open the owner's MusicSeed database.

After changing a surface or service, update its workflow guide as well as docstrings. A strict
build verifies rendering and references, but cannot prove narrative claims match behavior.
Use the CLI's documented-example parser and the API/MCP contract tests for relevant changes.
Keep the published documentation focused on current behavior; remove superseded design pages
and update links to the current guides.
