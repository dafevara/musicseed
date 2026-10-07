# Run MusicSeed in Docker

The root `Dockerfile` builds one image containing core, API, CLI, MCP, and the static web UI.
The default command runs the web UI and API on port 8789. CLI commands and MCP use the same
image and persistent state. No database server or process supervisor is required.

Containers share the host's Linux kernel (Docker Desktop supplies a Linux VM on macOS).
The image contains Alpine's small userspace, Python, shared libraries, and MusicSeed. Node
and npm are used in a separate build stage and are absent from the final image.

## Start the web UI

From the repository root, with Docker, BuildKit, and Docker Compose v2 available:

```bash
docker compose up --build -d
docker compose ps
```

Open <http://127.0.0.1:8789/setup/>. The named `musicseed-data` volume starts empty;
the setup wizard saves configuration and initializes the database there. Set a Plex URL
reachable from the container and provide access to its databases as described below.
On installations where Docker requires administrator access, prefix Docker commands with `sudo`.

Compose publishes the UI on the host's loopback interface. The process binds `0.0.0.0`
inside the container so Docker can forward requests to it. To reach the UI from other devices,
change the published address in `compose.yaml` to the desired trusted LAN interface and configure
`security.allowed_hosts` if you use a custom hostname. See [network access](local-runtime.md#ports).

```bash
docker compose logs --tail=100 musicseed
docker compose stop
docker compose start
```

`docker compose down` removes the container but keeps its named volume. Rebuilding or
recreating the container also keeps that volume. **Do not use `down --volumes` unless you intend
to delete MusicSeed's container configuration, credentials, library database, and cache.**

An image can also be built and run directly:

```bash
docker build -t musicseed:local .
docker run --rm --init --name musicseed \
  -p 127.0.0.1:8789:8789 -v musicseed-data:/data musicseed:local
```

The direct-run volume name is `musicseed-data`; Compose normally prefixes its volume name
with the Compose project name. Use the same launch method consistently to share state.

## What is cached

The build uses independent Python and web stages, then copies their results into the runtime.
Docker reuses unchanged layers; npm and uv also have BuildKit download caches. A pinned uv
binary installs Python packages during the build and is discarded before the runtime stage.

| Change | Work repeated |
|---|---|
| Python source or package metadata | Package the four small MusicSeed Python distributions; copy their layer. Third-party dependencies and web build stay cached. |
| Web source or build configuration | Run the static web build; copy its layer. npm installation and Python stages stay cached. |
| `web/package.json` or `web/package-lock.json` | Run `npm ci`, then rebuild the web UI. |
| `docker/requirements.txt` | Install Python dependencies and repackage the Python distributions. Web stages stay cached. |
| README/docs outside package README files | No application build layers change. |

After edits, use `docker compose up --build -d` again. This still assembles an updated image,
but does not reinstall dependencies or rebuild the unchanged surface. Docker is a packaged
runtime; use `scripts/dev.sh` for source hot reload.

`docker/requirements.txt` merges production dependencies from the four Python app lockfiles,
using the highest pinned version when they differ and retaining environment markers. It is
separate from `constraints.txt`, which remains the source installer's core/API/CLI pin set.
After changing Python dependencies and updating the relevant per-app `uv.lock` files, regenerate:

```bash
bash scripts/export-constraints.sh --docker
docker compose build
```

The package build runs `pip check` against the combined environment. Runtime dependencies
are installed with `--only-binary=:all:` so an absent Alpine wheel fails clearly instead of
silently building NumPy or cryptography with a large compiler toolchain. ARM64 and AMD64 are
the intended platforms; the image still needs a build and runtime check for the target platform.

The default bases are `python:3.12-alpine3.23` and `node:22-alpine3.23`. Python and Alpine
release lines are fixed; patch updates are selected on a fresh pull. Refresh base images with
`docker compose build --pull`, then `docker compose up -d`. An explicit base tag or digest can
be supplied through `PYTHON_IMAGE` and `NODE_IMAGE` build arguments. The build installer uses
`ghcr.io/astral-sh/uv:0.12.23` (overridable with `UV_IMAGE`). If a future dependency
stops providing musllinux wheels, a Debian slim Python base is an alternative, but the Alpine
package-install commands in the Dockerfile must also change.

Alpine packages use the official `https://dl-4.alpinelinux.org/alpine` mirror because the
default CDN did not resolve in the initial build environment. Override it with the
`ALPINE_MIRROR` build argument if needed.

## Persistent files and permissions

The runtime runs as `musicseed`, UID/GID 1000, with `/data` as its home directory. One volume
preserves all default paths without changing MusicSeed's configuration lookup:

| Container path | Contents |
|---|---|
| `/data/.config/musicseed/config.yaml` | Settings and credentials; saved atomically with mode 0600. |
| `/data/.local/share/musicseed/musicseed.db` | Library state and SQLite WAL sidecars. |
| `/data/.local/share/musicseed/logs/` | MusicSeed run logs. |
| `/data/.cache/musicseed/plex-dbs/` | Consistent snapshots fetched from a remote Plex host. |
| `/data/.ssh/` | Optional known hosts and SSH keys. |

Keep a configured `database.path` inside `/data` if it should survive container replacement.
Use a named volume for the simplest setup. A bind-mounted data directory must be writable
by the container user. To match a host user, build with explicit numeric IDs, for example:

```bash
docker build --build-arg MUSICSEED_UID=1001 --build-arg MUSICSEED_GID=1001 \
  -t musicseed:local .
```

Do not bind an existing host home directory as `/data`. A new container does not automatically
adopt the source installation's configuration or database. To migrate, stop every process using
the original database and make a [consistent backup](troubleshooting.md#database-backup-and-recovery),
then copy that backup and configuration into the volume with the correct ownership. Update
host-specific paths in the copied configuration. Mount a configuration **directory**, rather
than a single config file, because settings saves atomically replace the file.

## Plex networking and database access

Inside a bridge-networked container, `localhost` refers to that container. Use Plex's LAN IP
or a resolvable server hostname for `plex.url`. For Plex running on the Docker host, Docker
Desktop supports `host.docker.internal`; Linux can add:

```yaml
services:
  musicseed:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Then use `http://host.docker.internal:32400`, provided Plex listens on an interface reachable
from Docker. Plex sign-in and account-based server lookup work over outbound HTTP. LAN
multicast discovery and `.local` names may not work through the Docker bridge; a manual LAN IP
avoids depending on them. Native Linux host networking is an optional alternative, but removes
port forwarding and changes which interfaces are exposed.

The Plex HTTP API does not supply the SQLite library or sonic vectors. Choose one database source:

- **Remote Plex/NAS:** configure `plex.db_ssh_target`. The remote host must provide Python 3
  with SQLite and readable Plex databases. Populate the container user's verified
  `/data/.ssh/known_hosts`; host trust is not inherited from your host user. Mount a dedicated
  trusted SSH directory read-only at `/data/.ssh` for key authentication, or configure the
  optional password. Key files must be readable by the container UID. See
  [remote Plex DB access](local-runtime.md#remote-plex-db-access).
- **Local Plex or consistent backups:** bind mount the database directory read-only, for
  example `./plex-snapshots:/plex-dbs:ro`. Set `plex.db_path` to
  `/plex-dbs/com.plexapp.plugins.library.db` and `plex.blobs_db_path` to
  `/plex-dbs/com.plexapp.plugins.library.blobs.db`. Prefer consistent backups; reading a live
  WAL database through a read-only mount requires its existing sidecars to be accessible.
  Never copy live database/sidecar files sequentially and treat that as a consistent backup.

Host file permissions still apply to read-only mounts. No Plex database, token, SSH key, local
virtualenv, or log is included in the build context; `.dockerignore` allows only build inputs.

## CLI and MCP from the same image

The CLI works with the running container's volume:

```bash
docker compose exec musicseed musicseed-cli --help
docker compose exec musicseed musicseed-cli status
```

For a command without the web server running:

```bash
docker compose run --rm --no-deps musicseed musicseed-cli --help
```

An agent can launch MCP over stdio inside the running container. Use `-T` to keep the protocol
free of terminal formatting and an absolute Compose path so the agent's working directory
does not affect volume selection:

```json
{
  "mcpServers": {
    "musicseed": {
      "command": "docker",
      "args": ["compose", "-f", "/absolute/path/to/musicseed/compose.yaml",
               "exec", "-T", "musicseed", "musicseed-mcp"]
    }
  }
}
```

This requires Docker access without an interactive password prompt from the MCP host.
Alternatively, replace `exec` with `run`, insert `--rm --no-deps -T`, and keep
`musicseed musicseed-mcp` as the final arguments to start an on-demand container with the
same volume. Both modes share the configuration prepared through the web UI. MCP does not
run as a second background service in the default container.

## Smoke checks

After building and starting a fresh container:

```bash
docker compose ps
curl --fail http://127.0.0.1:8789/api/openapi.json >/dev/null
curl --fail http://127.0.0.1:8789/setup/ >/dev/null
docker compose exec musicseed musicseed-cli --help
docker compose exec musicseed musicseed-mcp --help
docker image inspect musicseed:local --format '{{.Size}}'
```

The health check reads the API schema using Python's standard library. It does not contact
Plex, initialize a database, or start an import. It assumes the default port and UI/API mode;
override or disable it if you change the container command. Restarting the container should
preserve setup and settings. To verify rebuild caching, rebuild unchanged, then make a Python
or web edit and check that the dependency installation steps report `CACHED`.
