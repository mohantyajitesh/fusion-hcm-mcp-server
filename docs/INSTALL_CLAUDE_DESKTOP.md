# Installing on Claude Desktop

How to run this MCP server locally and register it with Claude Desktop.

> **Mental model:** you don't install an "MCP client" — **Claude Desktop is the
> client**. You register this server in Claude Desktop's config file; Desktop
> then launches the server as a subprocess and talks JSON-RPC to it over
> stdin/stdout. Add the entry → restart Desktop → the tools appear.

There are two supported ways to run the server. Pick one:

| | Mode A — Python venv + keyring | Mode B — Docker |
|---|---|---|
| Best for | Local dev on your own machine | Matching the distributed artifact |
| Password storage | **OS credential store** (no plaintext) | Env var in Desktop config (plaintext on disk) |
| Needs | Python 3.11+ | Docker Desktop running |

---

## Prerequisites (both modes)

1. **Claude Desktop** installed (macOS or Windows).
2. The code on your machine — clone the repo, or download the ZIP from GitHub
   (green **Code** button → **Download ZIP**) and extract it. The extracted
   folder is named `fusion-hcm-mcp-server-main`.
3. **Network line-of-sight to your Fusion pod** — corporate VPN/firewall must
   allow HTTPS to `https://<pod>.fa.<datacenter>.oraclecloud.com`. Test the URL
   in a browser first. A generic Akamai 503 usually means a wrong pod host, not
   a server bug.
4. A **least-privilege Fusion integration user** (a dedicated test account with
   read-only HCM roles — never a personal login).

---

## Mode A — Python venv + OS credential store (recommended locally)

No plaintext password anywhere on disk.

### A1. Create the venv and install

macOS / Linux:
```bash
cd fusion-hcm-mcp-server-main
python3 -m venv .venv
source .venv/bin/activate
pip install ".[desktop]"        # includes keyring + truststore
```

Windows (PowerShell):
```powershell
cd fusion-hcm-mcp-server-main
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install ".[desktop]"
```

### A2. Store the password in the OS credential store

```bash
keyring set aj-fusion-hcm-mcp INTEGRATION_USER
# prompts for the password; stored in macOS Keychain / Windows Credential Manager
```

(`aj-fusion-hcm-mcp` is the service name the server looks up; the second
argument must equal the username you configure below.)

### A3. Create `config.toml`

Copy `config.example.toml` to `config.toml` in the project folder and set:

```toml
[server]
base_url = "https://your-pod.fa.us6.oraclecloud.com"   # your real pod host

[auth]
type = "basic"
username = "INTEGRATION_USER"
# no password line — it comes from the OS credential store
```

### A4. Sanity-check from a terminal (before touching Desktop)

```bash
.venv/bin/aj-fusion-hcm-mcp     # Windows: .venv\Scripts\aj-fusion-hcm-mcp.exe
```

It should start silently (stdio servers print nothing). `Ctrl+C` to stop. A
`Configuration error: ...` message tells you exactly what's missing.

### A5. Register in Claude Desktop

Find the absolute path of the console script:

- macOS/Linux: `realpath .venv/bin/aj-fusion-hcm-mcp`
- Windows: `(Resolve-Path .venv\Scripts\aj-fusion-hcm-mcp.exe).Path`

**Fully quit Claude Desktop first** (see Traps below), then edit:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "oracle-fusion-hcm": {
      "command": "/ABSOLUTE/PATH/TO/.venv/bin/aj-fusion-hcm-mcp",
      "env": {
        "CONFIG_FILE": "/ABSOLUTE/PATH/TO/fusion-hcm-mcp-server-main/config.toml"
      }
    }
  }
}
```

Only `CONFIG_FILE` goes in the env block — the password stays in the credential
store.

---

## Mode B — Docker

### B1. Build the image

```bash
cd fusion-hcm-mcp-server-main
docker build -t aj-fusion-hcm-mcp:latest .
```

### B2. Create `config.toml` (as in A3, but no password anywhere)

### B3. Register in Claude Desktop

**Fully quit Claude Desktop first**, then edit the config file (paths above):

```json
{
  "mcpServers": {
    "oracle-fusion-hcm": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env", "HCM_PASSWORD",
        "-e", "HCM_AUDIT_PATH=/app/audit/audit.jsonl",
        "-v", "/ABSOLUTE/PATH/TO/config.toml:/app/config.toml:ro",
        "-v", "/ABSOLUTE/PATH/TO/audit-dir:/app/audit",
        "aj-fusion-hcm-mcp:latest"
      ],
      "env": {
        "HCM_PASSWORD": "the-integration-user-password"
      }
    }
  }
}
```

Notes:
- **`-i` is essential** — the stdin/stdout pipe IS the MCP transport.
- The bare `--env HCM_PASSWORD` forwards the value from the `env` block into
  the container.
- ⚠️ In this mode the password sits **in plaintext** in
  `claude_desktop_config.json`. Use a throwaway test account, or prefer Mode A.
- Docker Desktop must be **running** before you launch Claude Desktop.

---

## Verify it works

Restart Claude Desktop and look for the tools icon (16 tools under
`oracle-fusion-hcm`). Then test in this order — each step isolates a layer:

| # | Ask Claude | Proves | Needs pod? |
|---|---|---|---|
| 1 | "Call server_info" | Server launches, config loaded | no |
| 2 | "List HCM resources for the talent module" | Seed catalog works | no |
| 3 | "Get capabilities" | Pod reachability + credentials | yes |
| 4 | "Describe the workers resource" | Live ADF `/describe` path | yes |
| 5 | "Find worker with person number 12345" | Real data (PII redacted) | yes |

If step 3 shows every module `unreachable` → network/URL problem. `no_access`
→ credentials/roles problem. That distinction is the point of testing in order.

---

## Traps (learned the hard way)

1. **Claude Desktop rewrites its config from memory on quit.** Edit
   `claude_desktop_config.json` only while Desktop is **fully closed**
   (macOS: Cmd+Q, check the menu bar; Windows: quit from the system tray) —
   otherwise your edits are silently overwritten.
2. **Freshly-set user env vars don't reliably reach Desktop-spawned
   processes.** That's why Mode A uses username-in-config +
   password-in-keyring instead of environment variables.
3. **Windows PowerShell 5.1 `-Encoding utf8` writes a BOM** that breaks JSON
   parsers. If you script the config file, write UTF-8 *without* BOM (or edit
   in a normal editor like VS Code / Notepad).
4. **JSON is unforgiving** — one trailing comma and Desktop just silently
   doesn't show the server. Validate the file if tools don't appear.
5. **Server not appearing at all?** Check Desktop's MCP logs:
   - macOS: `~/Library/Logs/Claude/mcp*.log`
   - Windows: `%APPDATA%\Claude\logs\`
6. **Corporate TLS inspection (Windows):** Mode A installs `truststore`, which
   makes the server use the OS certificate store automatically. In Docker
   (Mode B) the container trusts public CAs only — if your proxy re-signs TLS,
   use Mode A or mount your corporate CA bundle into the container.

---

## Where things land

- **Audit log:** `audit/audit.jsonl` relative to the server's working
  directory (Mode A) or the mounted audit dir (Mode B) — one JSONL line per
  tool/pod operation.
- **Safety defaults:** reads redact PII; writes and ATOM feeds are **off**
  until you set `features.writes_enabled` / `features.atom_enabled` in
  `config.toml`. Leave them off for first tests.
