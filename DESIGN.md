# Oracle Fusion HCM MCP Server — Technical Design

**Status:** Draft for review
**Date:** 2026-06-30
**Scope:** Phase 1 (read core + auth + discovery) designed in full; Phases 2–5 specified at the interface level.
**Product positioning:** A **distributable, reusable product** deployed across many Fusion HCM customers with varying licensing — *not* a single-customer integration (see §0).

---

## 0. Product positioning

This server is built to be **packaged once and reused across many Oracle Fusion HCM customers**, each with a different licensed module footprint, different flexfield customizations, and a different Oracle release.

Two consequences drive the whole design:

1. **Nothing customer-specific is hardcoded.** No fixed module list, no hand-coded schemas, no per-customer tool sets. The server learns each pod's reality at runtime via `/describe` + capability discovery (§12.3). `auto` discovery is the *contract*, not an optimization.
2. **One instance ↔ one pod (single-tenant deployment).** Each customer runs their own configured instance bound to one Fusion pod and one integration user. We do **not** build a multi-tenant server holding many customers' HCM credentials — that would be an unacceptable data-security and blast-radius risk for the most sensitive data in the enterprise. "Reusable across customers" means the *same distribution*, configured per deployment — not shared runtime state.

Everything below is written to honor those two constraints.

---

## 1. Goals & non-goals

**Goals**
- Let an AI model interact with Oracle Fusion HCM across its *entire* REST surface (~600 resources) without hand-coding a tool per resource.
- Ship as a **configurable, distributable product** that works on any customer's pod with zero code changes — only configuration.
- Be safe by default for the most sensitive data in the enterprise (comp, national IDs, health-related absences).
- Be self-documenting: the model introspects resources at runtime via Oracle's `/describe`.
- Phase cleanly toward writes, ATOM change-feeds, and BI Publisher.

**Non-goals (for now)**
- A UI. This is a server only.
- **Multi-tenant runtime** — one instance serves one pod (§0).
- Caching of HCM *data* (only schema/`describe` metadata is cached).
- Replicating BI Publisher report authoring — we only *invoke* reports (Phase 5).

---

## 2. Why a generic layer (the central bet)

Fusion HCM REST is built on Oracle's ADF REST framework. Every resource shares:

- Base path: `/hcmRestApi/resources/{version}/{resource}`
- Query grammar: `q`, `fields`, `expand`, `limit`, `offset`, `orderBy`, `onlyData`, `totalResults`
- A `/describe` endpoint returning schema, child collections, and supported actions
- Child navigation: `{resource}/{key}/child/{childResource}`
- Custom actions via `POST` with an `action` header / payload

Because the surface is uniform, **6 generic tools + ~15 curated workflow tools** cover what 600 hand-written tools would — without exploding the context window.

---

## 3. Authentication

Pluggable `AuthProvider` interface; selected via config.

| Provider | Use | Notes |
|---|---|---|
| `BasicAuthProvider` | Dev / quick start | Username + password, `Authorization: Basic`. Never for prod. |
| `OAuth2JwtProvider` | Production | Client-credentials / JWT-bearer against OCI IAM or IDCS. Token cache + auto-refresh on 401. |

**Interface**
```python
class AuthProvider(Protocol):
    async def headers(self) -> dict[str, str]: ...   # returns Authorization header
    async def refresh(self) -> None: ...             # called on 401
```

Config keys: `auth.type`, `auth.username`/`auth.password` (basic), or `auth.token_url`/`auth.client_id`/`auth.client_secret`/`auth.scope` (oauth2). Secrets come from env vars, never the config file.

---

## 4. The ADF REST client (`core/client.py`)

A single `httpx.AsyncClient` wrapper. Responsibilities:

- Inject auth headers; on `401`, call `refresh()` once and retry.
- **Defaults that protect context:** `onlyData=true`, `limit=25` (overridable, hard cap e.g. 500), encourage `fields=`.
- Transparent pagination helper: `iterate(resource, q, fields, max_records)` walks `offset`/`limit` until `hasMore=false` or `max_records` hit.
- Retry with backoff on `429`/`503`; surface `Retry-After`.
- Normalize Oracle error envelopes into a clean `HcmApiError(status, title, detail, o_errorpath)`.
- Strip Oracle HATEOAS `links` from responses by default (huge token sink) unless `include_links=true`.

---

## 5. Tool catalog

### Phase 1 — Read core (default ON)

#### `list_resources`
Search/enumerate the resource catalog.
```
list_resources(search: str | None = None, limit: int = 50)
-> [{ name, title, description }]
```
Source: a bundled catalog (mapped from Oracle Help Center docs in the docs-only phase), refreshed from the live pod's resource index when available.

#### `describe_resource`
Return a resource's schema so the model can build correct queries.
```
describe_resource(resource: str)
-> { name, attributes:[{name,type,filterable,updatable,required}],
     children:[name...], actions:[name...] }
```
Backed by the live `/describe` endpoint; **cached** (schemas are stable within a REST version).

#### `get_capabilities`
Report which modules/tool groups are live on this pod (see §12.3).
```
get_capabilities()
-> { module: provisioned | not_provisioned | no_access, ... }
```

#### `query_resource`  ← the workhorse
```
query_resource(
  resource: str,
  q: str | None = None,              # ADF filter expression (see §6)
  fields: list[str] | None = None,   # STRONGLY encouraged
  expand: list[str] | None = None,   # child collections to inline
  order_by: str | None = None,
  limit: int = 25,
  offset: int = 0,
  total_results: bool = False
) -> { items:[...], count, has_more, total? }
```

#### `get_record`
```
get_record(resource: str, key: str,
           fields: list[str] | None = None,
           expand: list[str] | None = None) -> { record }
```

### Phase 2 — Curated workflow tools (default ON)

Thin, named wrappers over `query_resource` for the top HR asks, so the model isn't composing `q=` for routine work:

- `find_worker(name|email|person_number|assignment_number)`
- `get_worker_profile(person_id, sections=[contact,assignment,comp,...])`
- `get_reporting_chain(person_id, direction=up|down, depth)`
- `get_current_compensation(person_id)`  *(redaction-gated, §7)*
- `list_absences(person_id, status, since)`
- `lookup_org(department|location|position|job, search)`
- `list_direct_reports(manager_person_id)`
- *(~8 more, finalized in Phase 2)*

### Phase 3 — Writes & actions (default OFF — `features.writes_enabled`)

```
mutate_record(resource, key?, op: create|update|delete,
              payload: dict, dry_run: bool = True)
run_action(resource, key, action: str, payload: dict, dry_run: bool = True)
```
Gates: feature flag off by default → `dry_run=True` default → returns a diff/preview → requires explicit `dry_run=False` to commit → every commit written to the audit log (§7).

### Phase 4 — ATOM change feeds (default OFF)
```
list_changes(feed: newhire|termination|empupdate|assignment,
             since: iso8601, limit)
-> [{ change_type, person_number, occurred_at, resource_link }]
```

### Phase 5 — BI Publisher / HCM Extracts (default OFF)
```
run_report(report_path, parameters: dict, format: xml|csv|json)
list_report_parameters(report_path)
```
Backed by BIP `ReportService` (SOAP) or the REST report endpoint; handles report bursting / chunked output.

---

## 6. The `q=` filter grammar (what we expose to the model)

ADF `q` is a RowSet filter. We document and validate a safe subset:

```
attr = value            person_number = 100010
attr LIKE 'Smith%'      LastName LIKE 'Sm%'
attr >= value           DateOfBirth >= "1990-01-01"
a = x and b = y         and / or, parenthesized
attr IN (a,b,c)
```

- `filters.py` validates attribute names against the cached `describe` schema (only `filterable=true` attrs) before sending — prevents malformed 400s and injection-ish mistakes.
- Values are quoted/escaped centrally.
- We surface Oracle's error `detail` verbatim when a filter is rejected, so the model can self-correct.

---

## 7. Safety model (applies from Phase 1)

Because **read access alone** exposes salaries and national IDs:

1. **Redaction policy** (`safety/redaction.py`): configurable field list (e.g. `NationalId`, `*Salary*`, `DateOfBirth`) is masked by default. Unmasking requires `features.sensitive_fields_enabled` + is audit-logged.
2. **Audit log**: every tool call records `{timestamp, tool, resource, key, caller, fields_returned, write?}`. Append-only, JSONL. Writes and sensitive reads are always logged.
3. **Writes**: off by default, `dry_run` default true, explicit commit, logged.
4. **Least privilege**: server documents the minimal Fusion role/scope needed; never assume admin.
5. **No data caching**: only `describe` schemas are cached; record data is never persisted.

---

## 8. Config (`config.py` / `config.toml` + env)

```toml
[server]
base_url      = "https://<pod>.fa.ocs.oraclecloud.com"
rest_version  = "11.13.18.05"      # pinned

[auth]
type = "oauth2"                    # or "basic"
# secrets via env: HCM_CLIENT_ID, HCM_CLIENT_SECRET, HCM_TOKEN_URL, ...

[features]
writes_enabled            = false
sensitive_fields_enabled  = false
atom_enabled              = false
bip_enabled               = false

# Module-mirrored tool groups (see §12). Core HR is always on; the rest are
# enabled only for what the customer has licensed + provisioned. `auto` lets
# capability discovery (§12.3) decide based on what the pod actually exposes.
[modules]
core_hr       = "on"      # Global Human Resources — universal baseline
compensation  = "auto"
absence        = "auto"
payroll       = "auto"
recruiting    = "auto"    # Oracle Recruiting Cloud (ORC)
talent        = "auto"    # Goals / Performance / Career / Succession
learning      = "auto"
benefits      = "auto"
time_labor    = "auto"

[limits]
default_limit = 25
max_limit     = 500
```

---

## 9. Error handling

- All Oracle errors → `HcmApiError` with `status`, `title`, `detail`, `errorpath`.
- `401` → one silent refresh+retry, then surface.
- `429/503` → backoff honoring `Retry-After`.
- Validation failures (bad attr in `q`/`fields`) caught *locally* against the schema cache and returned as actionable messages before any network call.

---

## 10. Open questions for review

1. **Auth target** — OCI IAM vs IDCS in your environment? Affects token endpoint shape.
2. **REST version** to pin for the docs-only build (default `11.13.18.05`)?
3. **Redaction defaults** — confirm the masked-field list and who can unmask.
4. **Workflow tool list** — is the Phase-2 top-15 the right set for your users?
5. **Deployment** — stdio (local to Claude Desktop/Code) vs HTTP/SSE (shared/hosted)? Changes the auth & audit story.
6. **BIP transport** — SOAP `ReportService` vs REST report endpoint availability on your pod.
7. ~~**Licensed modules**~~ — **Decided:** product is sold/reused across many customers with varying licensing, so the server leans entirely on `auto` capability discovery (§12.3) and hardcodes no module set. Remaining task is only to *validate probe resource names* (§12.4) against the pinned REST version during the live-pod phase.

---

## 11. Proposed build order

1. `config` + `auth` (Basic first, OAuth2 stub) + `core/client` with paging/error normalization.
2. `discovery` tools (`list_resources`, `describe_resource`) + schema cache.
3. **Capability discovery** (§12.3) — probe the pod, resolve `auto` modules.
4. `query_resource` + `get_record` + `filters` validation.
5. `safety` (redaction + audit) wired into the read path.
6. Smoke-test against docs-mapped fixtures; later swap in a live pod URL.

Phases 2–5 follow the interfaces above.

---

## 12. Licensing & module alignment

How the server stays aligned with how Oracle licenses, provisions, and updates Fusion HCM.

### 12.1 How Oracle licenses HCM (the facts that shape this design)

- Fusion Cloud HCM is sold **per-module on a per-employee-per-month (PEPM) subscription**, not as one monolith. Pillars are licensed independently: **Global Human Resources (Core HR)**, Talent, Recruiting (ORC), Learning, Compensation, Benefits, Payroll (+ localizations), Absence, Time & Labor, Journeys, Helpdesk, Health & Safety, etc.
- **REST APIs are not licensed or metered separately** — they're part of the SaaS subscription. No "API SKU," no per-call charge.
- The *real* API surface is gated by two things, not by an API license:
  1. Which **offerings/modules are provisioned and enabled** in Functional Setup Manager (FSM).
  2. The integration user's **role-based security (RBAC)** — job roles, duty roles, data-security policies.
- **OIC (Oracle Integration Cloud)** is separately licensed — we avoid it by going direct to REST.
- **BI Publisher, HCM Extracts, and ATOM feeds are included** in the SaaS; only the *roles* to author/run them must be granted.

> Caveat: exact SKU names, employee-count metrics, and bundle composition are contract-/ordering-document-specific and Oracle repackages periodically. Treat the *shape* below as reliable; confirm specific SKUs against the customer's Oracle ordering document.

### 12.2 Why the architecture already aligns

- **Auto-adapts to the licensed footprint** — `list_resources` + `describe_resource` probe the *actual pod*, so the server reflects exactly what's licensed and enabled. Unlicensed module → its resources simply aren't there. A one-tool-per-endpoint server would advertise tools that 403/404 for most customers; ours doesn't.
- **Handles per-customer flexfields** — DFF/EFF customizations surface as dynamic attributes in `/describe` and flow through the generic query layer for free.
- **Absorbs quarterly release drift** — pinned REST version + describe-at-runtime means new resources/attributes from each Oracle update (24A, 24B…) just appear.
- **RBAC-first** — least-privilege + writes-off-by-default mirror Oracle's own security model; the integration account's roles ultimately bound what's reachable.

### 12.3 Capability discovery (new startup step)

On startup (and on a TTL refresh), the server probes the pod to resolve which modules are actually live, then enables/disables the corresponding tool groups:

```
discover_capabilities() ->
  for each module in [modules] with value "auto":
     probe a representative resource (e.g. recruiting -> recruitingCEJobRequisitions)
     classify: provisioned | not_provisioned | no_access(403)
  cache result (TTL, e.g. 24h); expose via a `get_capabilities` introspection tool
```

- `core_hr = "on"` is assumed present (universal baseline) but still verified.
- Tools in a `not_provisioned`/`no_access` module **degrade gracefully** with an actionable message ("Recruiting not provisioned / integration user lacks access on this pod") instead of a raw 404/403.
- `auto` is the default so a single build works across customers with different licensing.

### 12.4 Module-mirrored tool groups

Tool groups map 1:1 to Oracle pillars (see `[modules]` in §8), so a deployment exposes only what it's licensed for:

| Tool group | Oracle module | Representative probe resource |
|---|---|---|
| `core_hr` | Global Human Resources | `workers`, `departments`, `jobs` |
| `compensation` | Compensation | `salaries`, `workforceCompensationPlans` |
| `absence` | Absence Management | `absences`, `absenceTypes` |
| `payroll` | Global Payroll | `payrollFlows`, `payrollRelationships` |
| `recruiting` | Recruiting (ORC) | `recruitingCEJobRequisitions` |
| `talent` | Talent | `workerGoals`, `performanceDocuments` |
| `learning` | Learning | `learnerLearningRecords` |
| `benefits` | Benefits | `benefitEnrollments` |
| `time_labor` | Time & Labor | `timeRecords` |

*(Probe resource names to be confirmed against the pinned REST version during the live-pod phase.)*

### 12.5 Strategic build order implication

Build the **Core HR baseline first** — workers, assignments, work structures, basic comp lookups. It's the one module essentially every Fusion HCM customer licenses, so Phase 1 + most of Phase 2 work **universally** regardless of which other modules a customer bought. Every other pillar becomes an opt-in, capability-gated tool group layered on top.

### 12.6 Distribution & per-customer onboarding

Because this is a distributable product (§0), onboarding a new customer must be **config-only, no code changes**:

1. **Deploy** the same artifact (container image / `pipx` package) into the customer's environment.
2. **Configure** `config.toml` + secrets: pod `base_url`, `rest_version`, auth (their IAM/IDCS client), feature flags. A `config.example.toml` ships in the repo.
3. **Run capability discovery** (`discover_capabilities`) — the server self-detects the licensed/provisioned footprint and lights up only the tool groups that work. No per-customer module list to maintain.
4. **Validate** against their pod: `get_capabilities` + a smoke-test of `describe_resource` on a few resources confirms roles and provisioning.

Design rules that keep it reusable:
- **No customer identifiers, SKUs, or schemas in code.** Everything specific lives in config or is discovered at runtime.
- **Graceful degradation everywhere** — a missing module or a role gap is a clear message, never a crash.
- **Version-tolerant** — pinned `rest_version` per deployment; describe-at-runtime absorbs attribute drift across Oracle releases.
- **Flexfield-agnostic** — DFF/EFF customizations are read from `/describe`, so each customer's custom attributes work with no changes.
- **Per-deployment audit log** — each instance owns its own audit trail; no cross-customer data ever shares a process (§0).

---

## 13. Implementation status & ADF ground truth

### 13.1 What is built (16 tools)

- **Diagnostics:** `server_info`
- **Discovery:** `list_resources` (seed + live index), `describe_resource` (attrs/children/actions/**child_actions**), `get_capabilities` (concurrent probes)
- **Read:** `query_resource`, `get_record`
- **Workflows:** `find_worker`, `get_worker_profile`, `list_direct_reports`, `get_reporting_chain`, `lookup_org`, `get_current_compensation`, `list_absences`
- **Change feeds:** `list_changes` (ATOM, gated by `features.atom_enabled`)
- **Writes:** `mutate_record`, `run_action` (gated by `features.writes_enabled`, dry-run default, schema-validated, audited)

**Client-layer safety floor:** the `HcmClient` has the redactor + audit injected, and every semantic operation runs through `_guarded` — so redaction and audit are inescapable even for a caller that bypasses the tools. Blocked/rejected writes are audited too.

### 13.2 ADF ground truth (pod-verified — do not "fix" these away)

1. Pod host is `<pod>.fa.<datacenter>.oraclecloud.com` (e.g. `.fa.us6.`); a wrong host returns a generic Akamai 503 (wrong URL, not a code bug).
2. Nested `expand` (`a.b.c`) returns grandchild collections **empty** — follow the child's HATEOAS link via `get_href`.
3. `onlyData=true` strips links server-side — `keep_links` must suppress `onlyData`.
4. `limit` propagates to **expanded child collections** — use a large limit when expanding (`_EXPAND_LIMIT = 200`).
5. Manager rows may lack `ManagerPersonId` (only `ManagerAssignmentNumber`) — resolve via default numbering `E<PersonNumber>`, verified by lookup.
6. Action envelope: `parameters` must be a **list of single key-value objects**; a combined object → 400.
7. Terminate `actionCode="TERMINATION"` works; `"RESIGNATION"` needs a paired `reasonCode`.
8. `absences` honors `q` only on person attributes — filter status/date client-side (lowercase attribute names).
9. Child-level actions are hidden unless `summarize_describe` surfaces `child_actions` (terminate/changeLegalEmployer live under `workRelationships`).
10. `emps`/`workers` REST key is a ~196-char composite hash from the item's `self` link, NOT PersonId — obtain via `query(..., keep_links=True)`.
11. `describe_catalog` is ~38MB — distilled to name/title immediately, never returned whole.
12. Some capability probes hang >60s — single-shot, 15s timeout, concurrent.
13. Redaction is substring keyword-based — idempotent; documented over/under-redaction by field name.
14. Diff RAW then redact — never redact before comparing (avoids falsely flagging unchanged sensitive fields).
15. `redact=False` is the client escape hatch, used only by the write-diff (which re-redacts).

---

## 14. Security model & known gaps

**Safe-by-default:** reads redacted unless `sensitive_fields_enabled`; writes off unless `writes_enabled`; dry-run default; the client-layer redaction+audit floor is inescapable. The real **authorization ceiling is the Oracle integration user's RBAC** — least-privilege that account.

**Known gaps (documented honestly):**
- **(a) No per-caller authorization** — any client with writes enabled can do anything the integration user can. Future: per-user SSO / delegated identity so Oracle enforces each user's RBAC. *Deferred.* OAuth2 today is a client-credentials **app** identity (super-user), not per-user.
- **(b) Module capabilities are reported, not enforced** — `get_capabilities` informs; it does not block queries to unlicensed modules (Oracle's own 404/403 does).
- **(c) HTTP transport is unauthenticated** — stdio only for production; HTTP/SSE is for trusted-network/dev use.
- **(d) Audit is local and untampered** — ship the JSONL to a SIEM for compliance retention/integrity.
- **(e) Redaction is keyword/substring-based** — over-redacts some fields (e.g. `SalaryBasisType`), under-redacts non-matching custom fields. Acceptable and documented; tune keywords per deployment.

**Tested auth:** basic (dev). **Deferred:** per-user delegated identity, capability enforcement, authenticated HTTP transport, SIEM audit shipping.
