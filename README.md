# Oracle Fusion HCM MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI models interact with **Oracle Fusion Cloud HCM** across its entire REST surface — workers, org structures, compensation, absence, payroll, recruiting, talent, learning and more — without hand-coding a tool per endpoint.

Built to be **packaged once and reused across many Fusion HCM customers**, regardless of which modules they license, how their flexfields are configured, or which Oracle release they run.

> ⚠️ **Status:** Early development. The technical design is complete ([DESIGN.md](DESIGN.md)). **Phase 1 read core is implemented** — discovery (`list_resources`, `describe_resource`, `get_capabilities`), generic read (`query_resource`, `get_record`), `q=` filter validation, and the safety layer (PII redaction + audit log). Pending validation against a live pod. Writes/ATOM/BIP follow in later phases.

---

## Why this exists

Oracle Fusion HCM exposes ~600 REST resources built on Oracle's uniform ADF REST framework. A naive MCP server would create one tool per resource and blow up the model's context window — and would advertise tools that don't exist for customers who haven't licensed the matching module.

This server takes the opposite approach: **a small set of generic, schema-aware tools** that introspect any resource at runtime via Oracle's `/describe` endpoint, plus a handful of curated workflow tools for the most common HR tasks. It discovers each customer's licensed footprint automatically and only exposes what actually works on their pod.

## Key design principles

- **Generic over hardcoded** — 6 generic tools + ~15 curated workflows cover all ~600 resources. No per-resource code.
- **Self-documenting** — the model reads live schemas via `describe_resource`; no bundled schema files to maintain.
- **Capability-aware** — startup probing detects which Oracle modules are licensed/provisioned and lights up only those tool groups (no Recruiting license → no Recruiting tools).
- **Safe by default** — read-only out of the box; writes are off by default, gated, dry-run-first, and audited. PII (national IDs, salary, DOB) is redacted unless explicitly enabled.
- **Distributable** — one configurable artifact, deployed single-tenant per customer pod. No customer specifics in code.

## Architecture at a glance

```
auth/     Basic + OAuth2/JWT (OCI IAM / IDCS)
core/     ADF REST client · resource catalog · /describe cache · q= filter builder
tools/    discovery · query · workflows · mutate · atom · bip
safety/   PII redaction · audit log · dry-run · confirm gates
config.py base URL · pinned REST version · scopes · feature & module flags
```

## Tools (Phase 1 read core)

| Tool | Purpose |
|---|---|
| `list_resources` | Search/enumerate the HCM resource catalog |
| `describe_resource` | Return a resource's schema, children, and actions (`/describe`) |
| `get_capabilities` | Report which modules are live on this pod |
| `query_resource` | Generic GET with `q`/`fields`/`expand`/paging — the workhorse |
| `get_record` | Fetch one record by key, optionally expanding children |

Writes (`mutate_record`, `run_action`), ATOM change-feeds, and BI Publisher tools are specified in the design and arrive in later phases — all off by default.

## Roadmap

| Phase | Deliverable |
|---|---|
| **1** | Generic read core + auth + discovery + safety scaffolding |
| **2** | ~15 curated HR workflow tools |
| **3** | Gated writes + custom actions + audit |
| **4** | ATOM change feeds (new hires, terminations, updates) |
| **5** | BI Publisher / HCM Extracts reporting |

## Stack

Python · [FastMCP](https://github.com/modelcontextprotocol/python-sdk) · `httpx` · `pydantic`
Packaged as a Docker/OCI image (primary) built from a hatchling wheel.

## Getting started

### Configure

```bash
cp config.example.toml config.toml   # then edit; supply secrets via HCM_* env vars
```

Required: `server.base_url` (or `HCM_BASE_URL`). Credentials should come from environment
variables (`HCM_USERNAME`/`HCM_PASSWORD`, or `HCM_CLIENT_ID`/`HCM_CLIENT_SECRET`/`HCM_TOKEN_URL`),
never the committed file. See [config.example.toml](config.example.toml).

### Run with Docker (primary)

```bash
docker build -t aj-fusion-hcm-mcp .
docker run --rm -i \
  -e HCM_BASE_URL="https://your-pod.fa.ocs.oraclecloud.com" \
  -e HCM_USERNAME="INTEGRATION_USER" -e HCM_PASSWORD="..." \
  -v "$PWD/config.toml:/app/config.toml:ro" \
  aj-fusion-hcm-mcp
```

For hosted HTTP transport, set `transport.type = "http"` (or `HCM_TRANSPORT=http`) and publish `-p 8000:8000`.

### Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
aj-fusion-hcm-mcp          # runs the MCP server over stdio
```

## Documentation

- **[DESIGN.md](DESIGN.md)** — full technical design: auth, the ADF REST client, exact tool signatures, the `q=` filter grammar, the safety model, and licensing/module alignment.

## Status & contributions

This is an actively developing project. The design doc is the source of truth; see open questions in [DESIGN.md §10](DESIGN.md).

## License

TBD.
