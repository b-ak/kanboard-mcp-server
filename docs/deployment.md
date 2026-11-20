# Setup guide: claude.ai, Claude mobile and Claude Code

This guide takes you from a running Kanboard to Claude creating and updating tasks on it, from
claude.ai, the Claude mobile apps and Claude Code. It was written against a Raspberry Pi 4 running
Kanboard in Docker behind a Cloudflare Tunnel, but works on any Docker host.

```
Claude (web / mobile / Code)
        │ HTTPS
        ▼
Cloudflare Tunnel ──▶ kanboard-mcp (Docker, :8000) ──▶ Kanboard (Docker, :80)
                       GitHub login + allowlist          your personal API token
```

- **Kanboard** keeps running as it is.
- **kanboard-mcp** runs next to it and talks to Kanboard's JSON-RPC API with your personal token.
- **Cloudflare Tunnel** gives kanboard-mcp a public HTTPS address without opening router ports.
- **GitHub OAuth** decides who may connect: only the GitHub accounts you list.

Only want Claude Code on the same machine as Kanboard? You don't need any of this: see
[README → stdio](../README.md#2-use-it-from-claude-code-on-the-same-machine-stdio).

## Contents

1. [Prepare Kanboard](#1-prepare-kanboard)
2. [Choose the public hostname and port](#2-choose-the-public-hostname-and-port)
3. [Create a GitHub OAuth App](#3-create-a-github-oauth-app)
4. [Create the env file](#4-create-the-env-file)
5. [Add kanboard-mcp to Docker Compose](#5-add-kanboard-mcp-to-docker-compose)
6. [Start it and verify on the host](#6-start-it-and-verify-on-the-host)
7. [Publish it over HTTPS with Cloudflare Tunnel](#7-publish-it-over-https-with-cloudflare-tunnel)
8. [Connect Claude](#8-connect-claude)

Then: [tell Claude when to use Kanboard](#tell-claude-when-to-use-kanboard) ·
[updating](#updating) · [troubleshooting](#troubleshooting) · [security notes](#security-notes) ·
[other setups](#other-setups)

## Before you start

You need:

- Kanboard running in Docker Compose (this guide assumes that; see [other setups](#other-setups)
  otherwise) and an account on it.
- A 64-bit Docker host with the compose plugin (Raspberry Pi OS 64-bit, Ubuntu arm64/amd64, …).
  Check with `uname -m`: `aarch64` or `x86_64`.
- A domain on Cloudflare with a tunnel, or another way to serve HTTPS (Tailscale Funnel,
  Caddy/nginx).
- A GitHub account.

Replace these placeholders everywhere below:

| Placeholder | Meaning |
|---|---|
| `kanboard-mcp.example.com` | Public hostname for the MCP server (new) |
| `kanboard.example.com` | Where you open Kanboard in a browser |
| `~/kanboard-stack` | Folder with the `docker-compose.yml` that runs Kanboard |
| `kanboard` | Kanboard's service name in that compose file |
| `your-kanboard-username` | Your Kanboard login name |
| `your-github-login` | Your GitHub username |

> **About `localhost`.** It always means *the machine (or container) you are on*. On the Docker
> host, `localhost:8100` may be Kanboard; in your laptop's browser it is your laptop; inside a
> container it is that container. Run the commands below **on the Docker host** unless a step says
> otherwise.

## 1. Prepare Kanboard

**Create a personal access token.** In Kanboard: your avatar (top right) → **My profile** → **API**
→ **Generate a new token**. Copy it.

> Don't use the token on **Settings → API**. That is the *application* token: it only works with
> the username `jsonrpc` and can reach every project. With your own username it fails with
> `401 Unauthorized`. The personal token acts as you and follows your project permissions.

**Set the Application URL.** **Settings** → **Application settings** → **Application URL** →
`https://kanboard.example.com/` (with the trailing slash) → **Save**. Kanboard builds task and board
links from this; if it is empty, the links Claude shows you point to `http://localhost/...`. The API
endpoint on your profile's API page should now read `https://kanboard.example.com/jsonrpc.php`.

## 2. Choose the public hostname and port

- **Hostname:** a new subdomain for the MCP server, e.g. `kanboard-mcp.example.com`. It must be
  separate from Kanboard's own hostname: each hostname routes to one service, and this one needs
  its own login (GitHub) rather than Kanboard's.
- **Port:** the server listens on `8000`. Check nothing else on the host uses it:

  ```bash
  ss -ltn | grep :8000
  ```

  No output means it's free. Otherwise pick another host port and use it in steps 5 and 7.

## 3. Create a GitHub OAuth App

GitHub → your profile picture → **Settings** → **Developer settings** (bottom of the left sidebar)
→ **OAuth Apps** → **New OAuth App**. It must be an *OAuth App*, not a *GitHub App*.

| Field | Value |
|---|---|
| Application logo | Optional. [`docs/logo.png`](logo.png) is ready to upload. |
| Application name | `Kanboard MCP` |
| Homepage URL | `https://kanboard-mcp.example.com` |
| Application description | Optional |
| Redirect URI (older form: *Authorization callback URL*) | `https://kanboard-mcp.example.com/auth/callback` |
| Allow wildcard matching | Off |
| Enable Device Flow | Off (the server uses the normal browser login) |
| Expire user access tokens | On. The server stores GitHub's refresh token and renews access tokens itself, so you are not logged out every 8 hours. |

Click **Register application**. Copy the **Client ID**, then click **Generate a new client secret**
and copy it immediately: GitHub shows it only once.

## 4. Create the env file

In the folder with Kanboard's compose file:

```bash
cd ~/kanboard-stack
nano kanboard-mcp.env
```

```dotenv
KANBOARD_USERNAME=your-kanboard-username
KANBOARD_API_TOKEN=<personal token from step 1>
MCP_AUTH=github
MCP_BASE_URL=https://kanboard-mcp.example.com
GITHUB_CLIENT_ID=<from step 3>
GITHUB_CLIENT_SECRET=<from step 3>
MCP_ALLOWED_GITHUB_USERS=your-github-login
```

Add a signing key for the server's own login tokens, and lock the file down:

```bash
echo "MCP_JWT_SIGNING_KEY=$(openssl rand -hex 32)" >> kanboard-mcp.env
chmod 600 kanboard-mcp.env
```

Set the signing key once and keep it: changing it logs out every connected client.

Leave `KANBOARD_URL` out of this file; the compose file sets it (next step), and a value in
`environment:` overrides the same variable in `env_file:`.

## 5. Add kanboard-mcp to Docker Compose

Add this service to the same `docker-compose.yml` that runs Kanboard:

```yaml
services:
  # ... your existing services, including kanboard ...

  kanboard-mcp:
    image: ghcr.io/b-ak/kanboard-mcp-server:latest
    container_name: kanboard-mcp
    restart: unless-stopped
    env_file: kanboard-mcp.env
    environment:
      KANBOARD_URL: http://kanboard     # Kanboard's service name; port 80 inside its container
    ports:
      - "127.0.0.1:8000:8000"           # host-only; the tunnel reaches it from the host
    volumes:
      - kanboard_mcp_data:/data         # GitHub logins survive restarts
    depends_on:
      - kanboard

volumes:
  # ... your existing volumes ...
  kanboard_mcp_data:
```

Why `http://kanboard` and not the port you open Kanboard on (e.g. `8100`): a mapping like
`"8100:80"` only applies to traffic coming from outside Docker. Containers in the same compose file
reach each other directly by service name on the container's own port, and Kanboard's container
listens on 80.

Check the file:

```bash
docker compose config --quiet    # prints nothing when the file is valid
```

## 6. Start it and verify on the host

```bash
docker compose pull kanboard-mcp
docker compose up -d kanboard-mcp
docker compose logs -f kanboard-mcp
```

Naming the service starts only kanboard-mcp, plus Kanboard if it isn't running or its settings
changed; your other services are left alone. Wait for `Uvicorn running on http://0.0.0.0:8000`, then press Ctrl+C (the
container keeps running). An `AuthlibDeprecationWarning` at the top is harmless. A line starting
with `Configuration error:` names the setting that is missing.

Run three checks:

```bash
# 1. The server answers locally
curl -s localhost:8000/.well-known/oauth-protected-resource/mcp

# 2. The server can reach Kanboard (expect 200 or 302)
docker exec kanboard-mcp python -c "import httpx;print(httpx.get('http://kanboard').status_code)"

# 3. Kanboard accepts your credentials (expect: 200 your-kanboard-username)
docker exec kanboard-mcp python -c "import os,httpx;r=httpx.post('http://kanboard/jsonrpc.php',auth=(os.environ['KANBOARD_USERNAME'],os.environ['KANBOARD_API_TOKEN']),json={'jsonrpc':'2.0','method':'getMe','id':1});print(r.status_code, r.json()['result']['username'] if r.status_code==200 else r.text[:200])"
```

Check 1 prints JSON containing `"resource":"https://kanboard-mcp.example.com/mcp"`. Check 3 is the
same call Claude makes first; if it prints `401`, see
[troubleshooting](#kanboard-rejected-the-credentials-401).

> After editing `kanboard-mcp.env`, run `docker compose up -d --force-recreate kanboard-mcp`.
> `docker compose restart` reuses the old container and does **not** re-read the env file.

## 7. Publish it over HTTPS with Cloudflare Tunnel

**You already have a tunnel on this host** (for Kanboard or anything else): add a route to it. In
the Cloudflare dashboard open the tunnel (**Networking → Tunnels → *your tunnel* → Routes → Add
route**; older dashboards: **Zero Trust → Networks → Tunnels → *your tunnel* → Public Hostname**)
and choose **Published application**:

| Field | Value |
|---|---|
| Subdomain | `kanboard-mcp` |
| Domain | `example.com` |
| Path | Empty (the server needs all of its paths: `/mcp`, `/authorize`, `/auth/callback`, …) |
| Service URL | `http://localhost:8000` (plain `http`; Cloudflare adds HTTPS on the public side) |

`localhost` is right when cloudflared runs **on the host** (e.g. as a systemd service). If
cloudflared runs as a container in the same compose file, use `http://kanboard-mcp:8000` instead.

**No tunnel yet:** **Networking → Tunnels → Create a tunnel** → *Cloudflared*, then either install
the connector on the host with the command the dashboard shows (it runs as a systemd service), or
run it from the compose file:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}   # put the token in the compose folder's .env
```

Then add the route as above. No router ports need to be opened.

The route can be added before the container is running; until then the hostname returns `502`.

Verify from anywhere:

```bash
curl -s https://kanboard-mcp.example.com/.well-known/oauth-protected-resource/mcp
```

You should get the same JSON as check 1. A `502` means the tunnel can't reach the Service URL: the
container isn't running or the port differs.

## 8. Connect Claude

### claude.ai and the Claude mobile apps

1. **Settings → Connectors → Add custom connector**.
2. Name `Kanboard`, URL `https://kanboard-mcp.example.com/mcp`. Leave the advanced OAuth fields
   empty: the server registers clients itself.
3. **Add**, then **Connect**. GitHub asks you to authorize *Kanboard MCP*; approve with
   **Authorize *your-github-login***. The screen may also list your GitHub organizations with
   *Grant* or *Request* buttons; leave them, as the server needs no organization access.
4. In a new chat, make sure Kanboard is enabled in the tools menu and ask:
   *"Run get_me on Kanboard."* It answers with your Kanboard username and `api_mode: user`.

Connectors added on claude.ai are also available in the mobile apps. By default claude.ai asks
before each tool that changes something (create, move, close, comment); read-only tools are marked
as such.

### Claude Code

Install Claude Code if `claude` isn't found:

```bash
curl -fsSL https://claude.ai/install.sh | bash   # then open a new terminal; claude --version
```

Add the server **for all your projects** (without `--scope user` it is registered for the current
folder only):

```bash
claude mcp add --scope user --transport http kanboard https://kanboard-mcp.example.com/mcp
```

Start `claude`, run `/mcp`, select **kanboard** → **Authenticate**, and approve in the browser.
`/mcp` then shows *Authentication successful. Connected to kanboard.* Ask *"run get_me on
Kanboard"* to confirm; it answers with your Kanboard username.

To check the scope, run `claude mcp list` from a different folder: `kanboard` should be listed
there too.

### Claude Desktop (local, no OAuth)

Running Claude Desktop on the same machine as Kanboard? Skip steps 2–7 — GitHub OAuth and a public
tunnel are only needed for the remote HTTP setup above. Claude Desktop launches the server itself
over stdio, so no OAuth, tunnel or Docker container is needed.

Add to `claude_desktop_config.json` (**Settings → Developer → Edit Config**):

```json
{
  "mcpServers": {
    "kanboard": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/b-ak/kanboard-mcp-server", "kanboard-mcp"],
      "env": {
        "KANBOARD_URL": "https://kanboard.example.com",
        "KANBOARD_USERNAME": "your-kanboard-username",
        "KANBOARD_API_TOKEN": "your-personal-api-token"
      }
    }
  }
}
```

Restart Claude Desktop; `kanboard` appears under the 🔌 tools icon. `MCP_TRANSPORT` defaults to
`stdio`, so nothing needs setting for it here. This only works for Claude Desktop: claude.ai, the
mobile apps and Claude Code all talk over HTTP to a server you host, not a local process, so they
need the setup in steps 1–8 above (Claude Code's own stdio option is in
[README → stdio](../README.md#2-use-it-from-claude-code-on-the-same-machine-stdio)).

## Tell Claude when to use Kanboard

Connecting gives Claude the tools; it doesn't tell it *when* to create or move tasks. Put your
rules in the `CLAUDE.md` of the project you work on (Claude Code) and in a claude.ai Project's
instructions. [`claude-md-template.md`](claude-md-template.md) is a starting point: read freely,
propose every board change and wait for your OK.

## Updating

```bash
cd ~/kanboard-stack
docker compose pull kanboard-mcp && docker compose up -d kanboard-mcp
```

`:latest` follows the newest build of `main`. To update only when you choose, pin a tag from the
[package page](https://github.com/b-ak/kanboard-mcp-server/pkgs/container/kanboard-mcp-server),
e.g. `ghcr.io/b-ak/kanboard-mcp-server:sha-d2bd491`.

## Troubleshooting

Look at the server's log first: `docker compose logs --tail 50 kanboard-mcp`. Don't paste the
output of `docker compose config` anywhere public; it contains your secrets.

#### `Configuration error: ...` in the log
The message names the missing setting, e.g. `MCP_AUTH=github requires: GITHUB_CLIENT_ID`. Fix the
env file, then `docker compose up -d --force-recreate kanboard-mcp`.

#### Kanboard rejected the credentials (401)
- You used the application token from **Settings → API**. Generate a personal token under
  **My profile → API** (step 1), or set `KANBOARD_USERNAME=jsonrpc` and `KANBOARD_DEFAULT_USER_ID`
  to use the application token deliberately.
- `KANBOARD_USERNAME` is your display name rather than your login name.
- You regenerated the token in Kanboard; the old one stops working.
- You edited the env file but used `docker compose restart`. Recreate instead (see above).

#### `Cannot reach Kanboard at http://kanboard/...`
kanboard-mcp is not in the same compose file as Kanboard, or Kanboard's service name differs. Use
the right service name, or see [other setups](#other-setups). Don't use the host port (`8100`)
with the service name.

#### `non-JSON response`
`KANBOARD_URL` points at something that isn't Kanboard (e.g. a login page or proxy).

#### `502` from `https://kanboard-mcp.example.com`
The tunnel route's Service URL doesn't reach the server: the container isn't running, the port
differs, or cloudflared runs in a container and needs `http://kanboard-mcp:8000`.

#### GitHub says `redirect_uri is not associated with this application`
The Redirect URI in the OAuth App must be exactly `https://kanboard-mcp.example.com/auth/callback`.

#### GitHub login succeeds but Claude still can't connect
Your GitHub login isn't in `MCP_ALLOWED_GITHUB_USERS`. Check with
`docker compose logs kanboard-mcp | grep Rejected`.

#### Login loop in claude.ai
`MCP_BASE_URL` must match the public URL exactly (`https://` and the same hostname). After changing
`MCP_JWT_SIGNING_KEY` or wiping the `kanboard_mcp_data` volume, remove and re-add the connector.

#### Task links point to `http://localhost/...`
Set Kanboard's Application URL (step 1).

#### `localhost:8100` works on the server but not in my browser
`localhost` in your browser is your own computer. Use `https://kanboard.example.com`, or
`http://<server-ip>:8100` if the port is published on the LAN.

#### Checks give unexpected results (a port in use, a response from something that isn't Kanboard)
Check the shell prompt: the commands must run on the Docker host, not on your laptop. Your laptop
can have its own services on the same ports.

#### `claude: command not found`, or the connector only appears in one project
Install Claude Code (step 8) and open a new terminal. Re-add the server with `--scope user`.

## Security notes

- Only the GitHub accounts in `MCP_ALLOWED_GITHUB_USERS` can use the server, even though any
  GitHub user can reach the login page.
- The server only needs your GitHub username. It currently requests GitHub's `user` scope, which
  GitHub shows as *Personal user data: full access*.
- The personal Kanboard token limits Claude to your projects and attributes its changes to you.
- Bind kanboard-mcp to `127.0.0.1` (as above) so it is only reachable through the tunnel. Do the
  same for Kanboard's published port (`"127.0.0.1:8100:80"`) if you only open it via the tunnel and
  kanboard-mcp reaches it by service name. Confirm with
  `docker ps --format "{{.Names}}  {{.Ports}}"`: each port should start with `127.0.0.1:`.
- Keep `kanboard-mcp.env` at mode `600` and out of git.

## Other setups

- **Kanboard is in Docker but in a different compose project:** either join both to a shared
  Docker network and keep `http://kanboard`, or use the published port via the host:
  `KANBOARD_URL: http://host.docker.internal:<published port>` together with
  `extra_hosts: ["host.docker.internal:host-gateway"]` (needed on Linux). This doesn't work if
  Kanboard's port is bound to `127.0.0.1`. The standalone
  [`docker-compose.example.yml`](../docker-compose.example.yml) is set up for this.
- **Kanboard runs elsewhere:** set `KANBOARD_URL` to its address, e.g.
  `https://kanboard.example.com`.
- **Without Docker:** `uv tool install git+https://github.com/b-ak/kanboard-mcp-server`, then run
  `kanboard-mcp --env-file /path/to/kanboard-mcp.env --transport http` from a systemd service
  (add `KANBOARD_URL` to the env file in that case).
- **Claude Code only, over a LAN or Tailscale:** skip GitHub and the tunnel with a shared secret:
  `MCP_AUTH=bearer`, `MCP_BEARER_TOKEN=$(openssl rand -hex 32)`, publish the port on the LAN, then
  `claude mcp add --scope user --transport http kanboard http://<host>:8000/mcp --header "Authorization: Bearer <token>"`.
  claude.ai and the mobile apps can't use this: they connect from the internet.
- **Another HTTPS front end** (Tailscale Funnel, Caddy, nginx): anything that terminates HTTPS for
  `kanboard-mcp.example.com` and forwards every path to port 8000 works the same way as step 7.
