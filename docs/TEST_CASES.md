# Test Cases & Production-Readiness Assessment

Oracle Fusion HCM MCP Server. This documents the read/write tool matrix, the
automated coverage, the manual/live checks needed against a pod, and an honest
production-readiness assessment.

## 1. Tool matrix (16 tools)

| Tool | Kind | Pod? | Redaction | Gate |
|---|---|---|---|---|
| `server_info` | diagnostic | no | n/a | — |
| `list_resources` | read (catalog) | only if `full_index` | n/a | — |
| `describe_resource` | read (schema) | yes | not PII | — |
| `get_capabilities` | read (probe) | yes | n/a | — |
| `query_resource` | read | yes | ✅ default | — |
| `get_record` | read | yes | ✅ default | — |
| `find_worker` | read (workflow) | yes | ✅ floor | — |
| `get_worker_profile` | read (workflow) | yes | ✅ floor | — |
| `list_direct_reports` | read (workflow) | yes | ✅ floor | — |
| `get_reporting_chain` | read (workflow) | yes | ✅ floor | — |
| `lookup_org` | read (workflow) | yes | ✅ floor | — |
| `get_current_compensation` | read (workflow) | yes | ✅ rows redacted | — |
| `list_absences` | read (workflow) | yes | ✅ floor | — |
| `list_changes` | read (ATOM) | yes | ✅ | `features.atom_enabled` |
| `mutate_record` | **write** | yes | diff redacted | `writes_enabled` + dry-run + schema |
| `run_action` | **write** | yes | — | `writes_enabled` + dry-run + schema |

## 2. Automated tests (offline, no pod) — 60 passing

| Suite | Covers |
|---|---|
| `test_config` | env override / defaults / missing base_url |
| `test_auth` | keyring fallback precedence, missing password → ConfigError, never-raises |
| `test_client_safety` | query redacts+audits; `redact=False` bypasses but still audits; write flagged; action in audit; failed op audited `error:<code>` then re-raised; sensitive flag; SSRF guard |
| `test_catalog` | seed search/filter; `summarize_describe` incl **child_actions** (CRUD excluded); live-index merge/dedupe |
| `test_filters` | extract / validate / build_q + quote-escape + bad-operator |
| `test_redaction` | masks / nested / disabled / variants |
| `test_workflows` | find_worker compacts + no PII + escaping; chain up via child link + PersonId; chain down levels; empty-chain note; effective_date pass-through; direct reports; comp wrapper-not-redacted-but-rows-are; absences person-only q + client-side filter; lookup_org unknown type |
| `test_atom` | parse feed + context; feature-gate off → note & no pod call; unknown feed rejected; date-only `since` expanded |
| `test_writes` | one test **per gate layer**: flag-off blocks; dry-run diffs RAW & doesn't write; unknown attr blocked; read-only blocked; fail-closed on missing schema; explicit commit writes+audits; run_action name validated via child_actions |

Run: `pytest -q`

## 3. Live checks (require a Fusion pod) — NOT yet run here

These validate the ADF ground truth (DESIGN §13.2) that cannot be checked offline:

- [ ] `get_capabilities` shows real modules `provisioned` (concurrent probes complete < tool timeout)
- [ ] `describe_resource workers` returns real attributes + `child_actions` on `workRelationships`
- [ ] `query_resource emps fields=[...]` returns real, redacted rows
- [ ] `find_worker` / `get_worker_profile` against a real person number
- [ ] `get_reporting_chain up` resolves managers via the assignment `managers` HATEOAS link
- [ ] `get_current_compensation` returns salary rows (amounts redacted)
- [ ] `list_absences` person-only query + client-side filter
- [ ] `list_changes` parses a real ATOM feed (with `atom_enabled`)
- [ ] `mutate_record` update **dry-run** shows a correct RAW diff on a real record
- [ ] `run_action terminate` dry-run validates against real `child_actions`
- [ ] A wrong-scope write returns Oracle's **403 unchanged** (RBAC ceiling holds)

## 4. Production-readiness assessment

| Dimension | Status | Notes |
|---|---|---|
| Read functionality | ✅ Built, unit-tested | Live-unverified |
| Write safety (4-layer gate) | ✅ Built, unit-tested | Off by default; live-unverified |
| Client redaction+audit floor | ✅ Built, unit-tested | Inescapable |
| Packaging (Docker + stdio) | ✅ Verified | Image boots, 16 tools |
| Live pod validation | ⛔ Not done | **Biggest gap** — needs a test pod |
| Per-caller authorization | ⛔ Deferred | RBAC is at the integration user (DESIGN §14a) |
| Capability enforcement | ⚠️ Reported not enforced | DESIGN §14b |
| HTTP transport auth | ⚠️ None | stdio only for prod (DESIGN §14c) |
| Audit durability | ⚠️ Local JSONL | Ship to SIEM for compliance (DESIGN §14d) |
| OAuth2 (prod auth) | ⚠️ Working stub | App identity; validate token flow on pod |

**Verdict:** Ready for **supervised user testing against a non-production pod with a least-privilege integration user**, reads-only (writes off). Not ready for production until the live-pod checklist (§3) passes and the deferred items in DESIGN §14 are addressed for the intended deployment.
