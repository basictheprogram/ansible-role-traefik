# Claude Code project notes — realtime.traefik

Deploys [Traefik v3](https://doc.traefik.io/traefik/) as a reverse proxy and
TLS edge on a single Docker host. DNS-01 ACME via RFC 2136 (works with BIND9,
Knot, PowerDNS, and any provider with a TSIG-authenticated update endpoint),
wildcard certs, and file-provider dynamic config are the primary use case.

---

## Behavioral guidelines

These four rules govern how to work in this repo. They bias toward
caution over speed — for trivial one-liner changes, use judgment.

### 1. Think before writing tasks

**Don't assume. Surface tradeoffs. Ask when uncertain.**

Before adding or changing anything:

* State assumptions explicitly. If a variable could live in `defaults/`,
  `vars/`, or `host_vars`, say which and why before choosing.
* If multiple approaches exist (e.g. `ansible.builtin.command` vs a
  purpose-built module), present the tradeoff — don't pick silently.
* If the request is ambiguous (which task file? which template block?),
  name the ambiguity and ask. Don't guess and implement.
* If a simpler approach solves the problem, say so and push back.
* If something conflicts with `DESIGN.md`, flag it before proceeding.

### 2. Simplicity first

**Minimum tasks, variables, and template logic that solve the problem.**

* No new default variables beyond what the task being added requires.
* No Jinja2 abstraction for logic used in only one template.
* No `when:` conditions for scenarios that have no test coverage.
* No "future-proofing" of the public interface that wasn't asked for.
* If a template block is 30 lines and could be 10, rewrite it.

Ask: would a senior Ansible engineer call this overcomplicated? If yes,
simplify.

### 3. Surgical changes

**Touch only what the request requires. Clean up only your own mess.**

When editing existing tasks, templates, or defaults:

* Don't reformat adjacent YAML, fix unrelated comments, or clean up
  upstream code that wasn't broken by your change.
* Match the existing style — indentation, quoting, bullet character —
  even if you'd do it differently from scratch.
* If you notice unrelated dead code or stale variables, mention it;
  don't delete it without being asked.

When your change creates orphans:

* Remove `vars`, `when` conditions, or template blocks that YOUR change
  made unreachable.
* Don't remove pre-existing orphans unless explicitly asked.

Every changed line should trace directly to the request.

### 4. Goal-driven execution

**Define the success criteria before starting. Verify before declaring done.**

Transform requests into verifiable outcomes:

* "Add a preflight assertion" → `molecule converge` passes,
  `molecule verify` passes, `pre-commit run --all-files` is clean.
* "Fix an idempotency bug" → second `molecule converge` reports zero
  changed tasks.
* "Refactor a template" → rendered output is byte-for-byte identical
  to pre-refactor output on a converged instance.

For multi-step changes, state a brief plan before starting:

    1. Edit template → verify: rendered YAML is valid
    2. Add task       → verify: molecule converge green
    3. Add test       → verify: molecule verify green
    4. Lint           → verify: pre-commit run --all-files clean

Strong success criteria allow independent verification. Weak criteria
("make it work") require constant clarification.

---

## Role-specific notes

### Source of truth

`DESIGN.md` is the authoritative spec. Read it before any non-trivial
change. If code disagrees with `DESIGN.md`, `DESIGN.md` is right —
flag the discrepancy and ask before fixing the design to match the code.

### Design notes

`DESIGN.md` covers: public interface variable schemas, static config
layout, TLS / ACME strategy (DNS-01 via IONOS, Route53, CloudFlare,
or RFC 2136), dynamic config file-provider structure, site routing
schema, wildcard cert schema, allowlist group model, inventory layout,
bootstrap sequence, migration path from hand-managed Compose, and
multi-region deployment model.

Key structural points:

* Traefik runs as a Docker Compose service. Static config is rendered
  to `{{ traefik_data_dir }}/traefik.yml`; dynamic config lives under
  `{{ traefik_dynamic_dir }}/`. Compose and `.env.secrets` live in
  `{{ traefik_compose_dir }}/`.
* Sites are defined in `host_vars` as a `traefik_sites` list. Each
  entry produces a router, a service, and (if allowlisted) an
  `ipAllowList` middleware in the dynamic file provider.
* Wildcard certs are declared in `traefik_wildcard_certs` and bound to
  a named resolver. Sites reference certs by name or inherit the
  default. Sites whose FQDNs span multiple cert specs emit one router
  per cert (named `<site>-<cert>`).
* The `traefik_proxy` Docker network is created by the role. All
  co-located containers that need routing must join it.

### Secrets

Role-specific secret variable names (vault on the consumer side; never
set in `defaults/`). The role templates all of these into
`{{ traefik_compose_dir }}/.env.secrets` (0600, root-owned). Only
populate variables for resolvers actually referenced by a cert.
Use `no_log: true` on any task that touches them.

* `traefik_ionos_api_key` — IONOS DNS API key; DNS-zone write scope.
* `traefik_route53_access_key_id` / `traefik_route53_secret_access_key`
  — AWS IAM key pair; needs `route53:GetChange`,
  `route53:ChangeResourceRecordSets`, `route53:ListHostedZonesByName`.
* `traefik_cloudflare_api_token` — CloudFlare scoped API token; DNS
  edit permission on the relevant zone.
* `traefik_rfc2136_tsig_api_key` — TSIG key for a BIND9/Knot/PowerDNS
  server that accepts RFC 2136 dynamic updates. CloudFlare and Route53
  do **not** support RFC 2136; use their native providers instead.

### Commit scopes

Role-specific subsystem scopes: `static-config`, `dynamic-config`,
`acme`, `tls`, `middlewares`, `routers`, `entrypoints`, `compose`,
`preflight`, `install`, `network`, `sites`, `service`, `verify`

### Settled decisions

These are locked in `DESIGN.md`. Don't propose alternatives unless
the human raises them:

* TLS = Let's Encrypt, **DNS-01 only**. No HTTP-01 path is built.
* DNS providers supported: IONOS, AWS Route53, CloudFlare, RFC 2136.
  RFC 2136 is a dynamic DNS update protocol (BIND9/Knot/PowerDNS);
  CloudFlare and Route53 have their own lego providers and do **not**
  use RFC 2136.
* Container runtime = Docker via
  `community.docker.docker_compose_v2`. No Swarm, no Kubernetes,
  no native systemd binary.
* Site scoping = `host_vars` only — one VM, one `traefik_sites`
  list.
* Allowlist groups = org-wide named CIDR sets; sites compose by
  reference (no copy-paste of IPs).
* Verification = container healthcheck only (`traefik healthcheck
  --ping`). No FQDN probing, no Traefik API introspection.
* `delay_before_check: 120` for IONOS and RFC 2136 (slow propagation);
  `0` for CloudFlare and Route53. Don't raise without measurement data.
* Firewall = upstream Fortigate. Role does not manage host firewalls.
* Network name = `traefik_proxy` (renamed from the legacy `dmz`
  network), created by the role.
* Per-resolver `acme-<name>.json` storage (one file per resolver,
  not one shared file).

### Open questions

If a task touches one of these, leave a `# TODO(open-q):` comment
linking to the section rather than guessing:

* Backup of `acme-*.json` files (out of scope for this role; needs
  a separate role / cron job).
* Multi-region rollout order.
* `delay_before_check` post-pilot tuning — 120 s is a defensive
  default; tune down once production propagation lag is measured.

#### HTTP-01 / cross-fire.org — RESOLVED 2026-06-11

`cross-fire.org` domain owner agreed to CloudFlare (full zone
delegation) and wildcard TLS. Both sites use the existing `cloudflare`
resolver. No role changes needed; HTTP-01 support is not required.

Consumer-side work needed (in the playbooks inventory, not this repo):
* Vault `traefik_cloudflare_api_token` for the `cross-fire.org` zone.
* Add a wildcard cert entry to `traefik_wildcard_certs`:
    - name: cross-fire-org
      resolver: cloudflare
      main: "*.cross-fire.org"
* Add sites to `traefik_sites`:
    - forum.cross-fire.org (migration from bookworm host; EoL 2026-06-30)
    - phpbb3.cross-fire.org (new site)
* Set `traefik_default_cert` if cross-fire.org is the only cert on that
  host, or leave existing default and pin `cert: cross-fire-org` on each
  site entry.

### Implementation order

Work one section at a time. Each item = one focused session and one
commit. Stop and verify between items.

Items marked ✅ are complete and should not be re-opened unless a
specific regression or design change requires it.

1. ✅ `meta/main.yml` — min_ansible_version 2.20, platforms all
   (Ubuntu, Debian), galaxy metadata.
2. ✅ `defaults/main.yml` — public interface block per DESIGN.md.
3. ✅ `vars/main.yml` — internal middleware library constants
   (`security-headers`, `compress`).
4. ✅ `templates/traefik.yml.j2` — static config; one
   `certificatesResolvers` block per entry in `traefik_acme_resolvers`.
5. ✅ `templates/compose.yml.j2` — container definition with
   healthcheck, journald logging, `env_file:` reference, ulimits,
   memory limits, optional CUPS port.
6. ✅ `templates/dynamic/middlewares.yml.j2` — org-wide library plus
   per-site `<name>-allowlist` middleware.
7. ✅ `templates/dynamic/sites.yml.j2` — routers + services +
   `serversTransports`; multi-cert split; per-site `entrypoints`.
8. ✅ `templates/dynamic/tls.yml.j2` — default store binding +
   `tls.options` (TLS 1.2/1.3, restricted ciphers).
9. ✅ `templates/env.secrets.j2` — `.env.secrets` rendered from
   resolver env blocks.
10. ✅ `tasks/preflight.yml` — assertions; cred presence uses
    `no_log: true`.
11. ✅ `tasks/install.yml` — directories, render compose +
    traefik.yml, write `.env.secrets`.
12. ✅ `tasks/network.yml` — `community.docker.docker_network` for
    `traefik_proxy`.
13. ✅ `tasks/sites.yml` — render the three dynamic templates.
14. ✅ `tasks/service.yml` — `community.docker.docker_compose_v2` up.
15. ✅ `tasks/verify.yml` — poll `docker inspect` until healthcheck
    `healthy`.
16. ✅ `tasks/main.yml` — orchestrates the above; legacy includes
    removed.
17. ✅ `handlers/main.yml` — `restart traefik` handler.
18. ✅ `molecule/default/` — platform matrix (Debian 12/13, Ubuntu
    22.04/24.04/26.04); testinfra verifier.
19. ✅ `README.md` — usage examples, docker-label convention, pointer
    to DESIGN.md.
20. ✅ `.github/workflows/ci.yml` — GitHub Actions CI + Galaxy
    import on semver tag.
21. Add molecule scenario for preflight failure cases (bad resolver
    reference, uncovered FQDN).
22. Add molecule scenario for multi-cert split (site FQDNs spanning
    two cert specs).
23. Add molecule scenario for `traefik_acme_enabled: true` with a
    mock RFC 2136 resolver.
24. Expand `molecule/default/tests/test_default.py` — verify dynamic
    config files are rendered, secrets file has mode 0600, container
    is healthy.

### Consumer side notes

This role is consumed from the playbooks repo (not this repo).
Inventory layout, vault structure, and the proxy host's
`traefik_sites` mapping are described in `DESIGN.md` §"Inventory
layout" and §"Migration: hand-managed Docker Compose → role-managed".
When asked about consumer-side changes, ask which inventory repo to
operate on — it is not in this directory tree.

---

## Conventions

* **Commits**: follow the commit message guide in this file exactly.
  Conventional Commits, imperative mood, bodies wrapped at 72,
  asterisk bullets.
* **Lint**: `.ansible-lint`, `.yamllint`, `.pre-commit-config.yaml`
  define the rules. Run `pre-commit run --all-files` before declaring
  work done.
* **Secrets**: never write a credential into a tracked file. Vault
  secrets are consumed on the consumer side; the role templates them
  into config files with restricted permissions. Use `no_log: true`
  on any task that touches them.
* **Modules**: prefer FQCNs (`ansible.builtin.template`,
  `community.docker.docker_compose_v2`, `community.docker.docker_network`).
  The `.ansible-lint` rules require it.
* **Idempotency**: every task should be safe to re-run.

## Testing locally

* `pre-commit run --all-files` — fast lint/format pass. Run before
  every commit.
* `molecule converge` then `molecule verify` — fast iteration during
  template / task work; skips the destroy/create cycle.
* `molecule test` — full role exercise per platform. Slow; run
  before declaring a change done.

## Test framework — testinfra

The verifier is **testinfra** (`pytest-testinfra`), not the Ansible
verifier. Tests are written in Python and live in:

    molecule/default/tests/test_default.py

Import `Host` from `testinfra.host` for type annotations, guarded by
`TYPE_CHECKING`:

    from __future__ import annotations
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from testinfra.host import Host

    def test_example(host: Host) -> None:
        assert host.file("/etc/traefik").exists

All test functions must be annotated `host: Host` and return `-> None`.
Install dependencies: `pip install -r molecule/default/requirements.txt`.

## When in doubt

Read `DESIGN.md`, then ask. The schemas and decisions there are
load-bearing.

---

## Commit message guide

You are an expert DevOps engineer and professional git commit message
writer. When generating a commit message, follow these steps exactly.

### Step 1 — Retrieve changes

Run:

    git diff --cached

Analyze the full staged diff. This is the **single source of truth**
for what will be committed.

### Step 2 — Understand the change

Determine:

* The **primary purpose** of the change
* The **type of change** (feature, bug fix, refactor, etc.)
* The **most relevant scope** within the role
* Whether the change introduces a **breaking change** for role consumers
* Whether multiple changes should be summarized together

Pay special attention to:

* Changes to `defaults/main.yml` — these define the role's public interface
* Changes to handler names, task names, and tags — consumers may pin to them
* Changes to template variables that consumers override
* Changes to config or env file templates that affect service behavior
* Changes to `meta/main.yml` — galaxy metadata, min Ansible version, platforms

If multiple files are modified, identify the **dominant intent** rather
than listing every file.

### Step 3 — Select commit type

Use Conventional Commits:

* `feat` — new task, handler, variable, template, or capability
* `fix` — bug fix or idempotency correction
* `docs` — README, role metadata documentation, inline comments
* `style` — YAML formatting, whitespace, ansible-lint cleanup
* `refactor` — restructure tasks/templates without behavior change
* `perf` — performance improvement (e.g., reduced task runs, fewer handlers)
* `test` — molecule scenarios, lint config, CI tests
* `chore` — galaxy metadata, dependencies, tooling
* `ci` — GitHub Actions, GitLab CI, pre-commit hooks

### Step 4 — Determine scope

Infer a scope from the role layout or the subsystem being changed.

Common Ansible role scopes: `tasks`, `handlers`, `templates`,
`defaults`, `vars`, `meta`, `molecule`, `docker`.

Role-specific subsystem scopes: `static-config`, `dynamic-config`,
`acme`, `tls`, `middlewares`, `routers`, `entrypoints`, `compose`,
`preflight`, `install`, `network`, `sites`, `service`, `verify`

Only include a scope when it adds clarity. Prefer a subsystem scope
for feature-driven changes (e.g., `feat(acme): ...`) and a role-layout
scope for structural changes (e.g., `refactor(tasks): ...`).

### Step 5 — Write the commit message

Format exactly as:

    <type>[optional scope]: <short summary (<=50 chars)>

    <body wrapped at 72 characters>

    [optional footer(s)]

**Subject line rules:**

* Use **imperative mood** ("Add", "Fix", "Update", "Remove")
* Maximum **50 characters**
* Describe the **result**, not the implementation
* Prefer role-specific or Ansible terminology over generic phrasing

**Body rules** (required):

Explain **why the change was made**, focusing on:

* What deployment scenario or upstream behavior motivated it
* What downstream role consumers need to know to upgrade safely
* Any Ansible version constraints involved

When helpful, summarize key changes using bullet points.

**Bullet rules:**

* Use `*` (asterisk) for all bullets — never `-` or `•`
* Nested bullets indented with two spaces
* No Markdown formatting of any kind

**Ansible role expectations:**

* Call out new, renamed, or removed default variables
* Note when handler names, tag names, or public task names change
* Mention idempotency improvements when relevant
* Reference supported platforms when adding OS-specific tasks
* Flag changes to `meta/main.yml` (min Ansible version, platforms)
* Note molecule scenario additions or removals

**Traefik-specific expectations:**

* Distinguish between **static configuration** (requires restart) and
  **dynamic configuration** (hot-reloaded by the file provider)
* Note the minimum Traefik version when using new directives
* Call out new providers, middlewares, routers, or entrypoints by name
* Highlight TLS or ACME changes that affect certificate issuance or
  renewal

### Breaking changes

A change is breaking when it:

* Renames or removes a default variable
* Renames or removes a handler, tag, or public task name
* Changes a default value in a way that alters runtime behavior
* Drops support for an Ansible version or OS platform
* Restructures generated configuration in a way consumers' overrides
  cannot accommodate

If the diff introduces a breaking change:

* Add `!` after the type/scope in the subject
* Include a footer: `BREAKING CHANGE: <description>`

Examples:

    feat(acme): add DNS-01 challenge support via RFC 2136
    fix(dynamic-config): correct middleware ref in router
    refactor(tasks): split install and configure into files
    chore(meta): bump minimum Ansible version to 2.20
    test(molecule): add scenario for Ubuntu 24.04

    feat(defaults)!: rename traefik_acme_email variable

    BREAKING CHANGE: traefik_acme_email is now
    traefik_acme_account_email; update playbook vars before upgrading.

### Step 6 — Output rules

Return **only the commit message**. Do NOT include:

* explanations or analysis
* the diff
* markdown formatting
* code fences

The output must be a clean commit message ready for `git commit`.
It will be pasted directly into a git commit editor — optimize for
copy/paste fidelity over styling.
