# Deploying on a Raspberry Pi (or any Docker host)

This guide runs the MCP server next to Kanboard and publishes it over HTTPS so claude.ai, the Claude
mobile apps and Claude Code can all use it.

Requirements: 64-bit OS (Raspberry Pi OS 64-bit / Ubuntu arm64), Docker with the compose plugin, and a
domain you can point at a Cloudflare Tunnel. You can use Tailscale Funnel or Caddy/nginx instead;
anything that terminates HTTPS and forwards to port 8000 works.

## 1. Pick the public URL

For example `https://kanboard-mcp.example.com`. This is `MCP_BASE_URL`, and the MCP endpoint is
`https://kanboard-mcp.example.com/mcp`.

## 2. Create a GitHub OAuth app

GitHub → *Settings → Developer settings → OAuth Apps → New OAuth App*:

- Homepage URL: `https://kanboard-mcp.example.com`
- Authorization callback URL: `https://kanboard-mcp.example.com/auth/callback`

Copy the client ID and generate a client secret.

## 3. Configure

```bash
mkdir -p ~/kanboard-mcp && cd ~/kanboard-mcp
curl -fsSLO https://raw.githubusercontent.com/b-ak/kanboard-mcp-server/main/docker-compose.example.yml
mv docker-compose.example.yml docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/b-ak/kanboard-mcp-server/main/.env.example -o .env
chmod 600 .env
```

Edit `.env`:

```dotenv
KANBOARD_USERNAME=your-username
KANBOARD_API_TOKEN=...
MCP_AUTH=github
MCP_BASE_URL=https://kanboard-mcp.example.com
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
MCP_ALLOWED_GITHUB_USERS=your-github-login
MCP_JWT_SIGNING_KEY=<output of: openssl rand -hex 32>
```

In `docker-compose.yml`, set `KANBOARD_URL` to wherever Kanboard is reachable **from inside the
container**:

- Kanboard runs in Docker on the same Pi: join its network and use its service name. Add an
  external network to both services, or put the MCP service in Kanboard's compose file and use
  `http://kanboard`.
- Kanboard publishes a port on the Pi: use `http://host.docker.internal:<port>`.
- Kanboard is elsewhere: use its URL (`https://kanboard.example.com`).

## 4. Start it

```bash
docker compose up -d
docker compose logs -f kanboard-mcp
curl -s localhost:8000/.well-known/oauth-protected-resource/mcp   # should print JSON
```

The image is multi-arch (amd64/arm64) and published to `ghcr.io/b-ak/kanboard-mcp-server`. To
build locally instead, replace `image:` with `build: .` in a clone of the repo.

## 5. Publish it over HTTPS (Cloudflare Tunnel)

In the Cloudflare dashboard: *Zero Trust → Networks → Tunnels → Create tunnel*. Add a public hostname
`kanboard-mcp.example.com` → service `http://kanboard-mcp:8000` (if cloudflared runs in the same
compose file) or `http://localhost:8000` (if it runs on the host). Put the tunnel token in `.env` as
`CLOUDFLARE_TUNNEL_TOKEN`, uncomment the `cloudflared` service and run `docker compose up -d` again.

No router ports need to be opened.

## 6. Connect Claude

- **claude.ai / mobile:** *Settings → Connectors → Add custom connector* →
  `https://kanboard-mcp.example.com/mcp` → sign in with GitHub.
- **Claude Code:** `claude mcp add --transport http kanboard https://kanboard-mcp.example.com/mcp`,
  then `/mcp` to sign in.

## Alternatives

- **No public URL (Claude Code only):** run Claude Code on the Pi and use stdio (see the README).
  Or reach the Pi over Tailscale or a LAN with `MCP_AUTH=bearer`:
  `claude mcp add --transport http kanboard http://pi:8000/mcp --header "Authorization: Bearer <token>"`.
- **Without Docker:** `uv tool install git+https://github.com/b-ak/kanboard-mcp-server`, then
  run `kanboard-mcp --env-file /path/to/.env --transport http` from a systemd service.

## Troubleshooting

- `Kanboard rejected the credentials`: wrong username/token pair, or a proxy in front of Kanboard
  strips the `Authorization` header (configure the proxy to pass it through).
- `non-JSON response`: `KANBOARD_URL` points at the wrong place (e.g. a login page).
- Login loop in claude.ai: check that `MCP_BASE_URL` exactly matches the public URL and that the
  GitHub callback URL ends in `/auth/callback`.
- After changing `MCP_JWT_SIGNING_KEY` or wiping the `/data` volume, remove and re-add the connector.
