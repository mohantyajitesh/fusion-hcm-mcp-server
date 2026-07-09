# Oracle Fusion HCM MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI models interact with **Oracle Fusion Cloud HCM** across its entire REST surface — workers, org structures, compensation, absence, payroll, recruiting, talent, learning and more — without hand-coding a tool per endpoint.

Built to be **packaged once and reused across many Fusion HCM customers**, regardless of which modules they license, how their flexfields are configured, or which Oracle release they run.

> ⚠️ **Status:** Feature-complete build, **pending live-pod validation**. All **16 tools** are implemented (discovery, generic read, 7 curated workflows, ATOM change feeds, and gated writes), with an inescapable client-layer redaction + audit floor. 60 unit tests pass; the Docker image and stdio server boot with all 16 tools. The one open gap is validation against a real Fusion pod — see [docs/TEST_CASES.md](docs/TEST_CASES.md) §3 and [DESIGN.md](DESIGN.md) §13–§14.

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

## Tools (16)

| Group | Tools |
|---|---|
| Diagnostics | `server_info` |
| Discovery | `list_resources` · `describe_resource` · `get_capabilities` |
| Read | `query_resource` · `get_record` |
| Workflows | `find_worker` · `get_worker_profile` · `list_direct_reports` · `get_reporting_chain` · `lookup_org` · `get_current_compensation` · `list_absences` |
| Change feeds | `list_changes` (ATOM — gated by `features.atom_enabled`) |
| Writes | `mutate_record` · `run_action` (gated by `features.writes_enabled`, dry-run default, schema-validated) |

The generic `query_resource` / `get_record` / `describe_resource` work against **any** of the ~600 HCM resources; the workflows are curated shortcuts for common HR questions.

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| **1** | Generic read core + auth + discovery + safety floor | ✅ Built |
| **2** | Curated HR workflow tools | ✅ Built |
| **3** | Gated writes + custom actions + audit | ✅ Built |
| **4** | ATOM change feeds | ✅ Built |
| **live** | Validation against a real Fusion pod | ⛔ Pending |
| **5** | BI Publisher / HCM Extracts reporting | ◻ Future |

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
