# Claude Code project notes — ansible-role-traefik

This is an Ansible role that deploys Traefik v3 as a reverse proxy /
TLS edge at regional offices. Forked from arillso/ansible.traefik
(itself a fork of sbaerlocher/ansible.traefik), being modernized for
`ansible-core` 2.20, Traefik v3, Debian 12/13, Ubuntu 22.04/24.04,
and a multi-region deployment model.

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

## Source of truth

**`DESIGN.md`** in this repo is the authoritative spec for the new
role. Read it before making any non-trivial change. Variable names,
schemas, file layout, bootstrap sequence, TLS strategy, and migration
plan all live there.

If something in the code disagrees with `DESIGN.md`, `DESIGN.md` is
right unless explicitly told otherwise — flag the discrepancy and
ask before "fixing" the design to match the code.

## Repo state

The code currently in `tasks/`, `defaults/`, `templates/` is inherited
upstream (Traefik v2-era, HTTP-01, single-host model). It is being
**replaced**, not incrementally edited:

* The new task layout is `preflight.yml`, `install.yml`,
  `network.yml`, `sites.yml`, `service.yml`, `verify.yml`. Legacy
  `tasks/0_config.yml` and `tasks/1_setup.yml` get removed once their
  replacements land.
* `defaults/main.yml` is being replaced wholesale with the public
  interface block from `DESIGN.md` — old names (`traefik_qs_*`,
  `traefik_confkey_*`) are not preserved.

This is a breaking change to the role's public interface. Per the
commit conventions below, breaking-change commits get the `!` marker
and a `BREAKING CHANGE:` footer.

## Conventions

* **Commits**: follow the commit message guide in this file exactly.
  Conventional Commits, imperative mood, bodies wrapped at 72,
  asterisk bullets.
* **Lint**: `.ansible-lint`, `.yamllint`, `.pre-commit-config.yaml`
  define the rules. Run `pre-commit run --all-files` before declaring
  work done.
* **Secrets**: never write a credential into a tracked file. The role
  expects `traefik_ionos_api_key`, `traefik_route53_access_key_id`,
  `traefik_route53_secret_access_key`, `traefik_cloudflare_api_token`
  in vaulted vars on the consumer side; the role itself templates
  them into a `0600` env file at `{{ traefik_compose_dir }}/.env.secrets`
  and references it from compose. Use `no_log: true` on any task
  that touches them.
* **Modules**: prefer FQCNs (`community.docker.docker_compose_v2`,
  `ansible.builtin.template`, `community.docker.docker_network`).
  The `.ansible-lint` rules require it.
* **Idempotency**: every task should be safe to re-run. Templates
  use `validate:` where Traefik provides a syntax checker; otherwise
  rely on Traefik's `watch: true` reload + the verify step to catch
  bad output.

## Implementation order

Work one section at a time. Each item below = one focused session
and one commit. Stop and verify (lint + molecule converge) between
items.

1. `meta/main.yml` — bump `min_ansible_version` to 2.20, update
   `platforms` (Debian 12/13, Ubuntu 22.04/24.04), galaxy metadata.
2. `defaults/main.yml` — replace with the public interface block
   from `DESIGN.md` §"Public interface".
3. `vars/main.yml` — internal constants for the org-wide middleware
   library (`security-headers`, `compress`) per `DESIGN.md`
   §"Org-wide middleware library".
4. `templates/traefik.yml.j2` — static config per `DESIGN.md`
   §"Static config" and §"TLS / ACME". Renders one
   `certificatesResolvers` block per entry in
   `traefik_acme_resolvers`.
5. `templates/compose.yml.j2` — container definition with
   healthcheck, journald logging, `env_file:` reference to
   `.env.secrets`, ulimits, memory limits per the defaults block.
6. `templates/dynamic/middlewares.yml.j2` — org-wide library plus
   one `<site>-allowlist` middleware per site with a non-empty
   allowlist (union of referenced groups, deduped, comments
   preserved).
7. `templates/dynamic/sites.yml.j2` — routers + services +
   `serversTransports`. Implements the multi-cert split rule from
   `DESIGN.md` §"`traefik_wildcard_certs`" notes (sites whose FQDNs
   span multiple cert specs emit one router per cert, named
   `<site>-<cert>`).
8. `templates/dynamic/tls.yml.j2` — default store binding +
   `tls.options` (modern profile: TLS 1.2/1.3, restricted ciphers).
9. `tasks/preflight.yml` — assertions per `DESIGN.md` §"Bootstrap &
   lifecycle" step 1. Cred presence asserts use `no_log: true`.
10. `tasks/install.yml` — directories, render compose + traefik.yml,
    write `.env.secrets`.
11. `tasks/network.yml` — `community.docker.docker_network` for
    `traefik_proxy`.
12. `tasks/sites.yml` — render the three dynamic templates.
13. `tasks/service.yml` — `community.docker.docker_compose_v2` up.
14. `tasks/verify.yml` — poll `docker inspect` until healthcheck
    `healthy`, fail after `traefik_verify_healthcheck_timeout`.
15. `tasks/main.yml` — orchestrate the above; remove legacy
    includes.
16. `handlers/main.yml` — `restart traefik` triggered only by
    `compose.yml` or `traefik.yml` changes (dynamic config is
    hot-reloaded).
17. Delete `tasks/0_config.yml` and `tasks/1_setup.yml` and any now-
    orphaned templates from the upstream fork.
18. `molecule/default/` — update `molecule.yml` for the platform
    matrix (Debian 12, Debian 13, Ubuntu 22.04, Ubuntu 24.04) and
    `playbook.yml` to provide minimal valid `traefik_sites`,
    `traefik_acme_resolvers`, and `traefik_wildcard_certs`. ACME
    against LE staging or use `traefik_acme_enabled: false` for
    pure-template tests.
19. `README.md` — usage examples mirroring `DESIGN.md` schemas, the
    docker-label convention for co-located containers, a pointer to
    `DESIGN.md` for full architecture.
20. `.travis.yml` → GitHub Actions (separate effort; flag when
    ready, don't bundle into the role refactor).

## Settled decisions — don't re-litigate

These are locked in `DESIGN.md`. Don't propose alternatives unless
the human raises them:

* TLS = Let's Encrypt, **DNS-01 only**, multi-resolver (IONOS,
  Route53, CloudFlare). No HTTP-01 path is built.
* Container runtime = Docker via
  `community.docker.docker_compose_v2`. No Swarm, no Kubernetes,
  no native systemd binary.
* Site scoping = `host_vars` only — one VM, one `traefik_sites`
  list.
* Allowlist groups = org-wide named CIDR sets; sites compose by
  reference (no copy-paste of IPs).
* Verification = container healthcheck only (`traefik healthcheck
  --ping`). No FQDN probing, no Traefik API introspection.
* IONOS `delay_before_check: 120` — IONOS propagation is genuinely
  slow. Don't lower without measurement data.
* Firewall = upstream Fortigate. Role does not manage host
  firewalls.
* Network name = `traefik_proxy` (renamed from the legacy `dmz` network),
  created by the role.
* Per-resolver `acme-<name>.json` storage (one file per resolver,
  not one shared file).

## Open questions tracked in DESIGN.md

If a task touches one of these, leave a `# TODO(open-q):` comment
linking to the section rather than guessing:

* Backup of `acme-*.json` files (out of scope for this role; needs
  a separate role / cron job).
* Multi-region rollout order.
* IONOS `delay_before_check` post-pilot tuning.

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

### Why testinfra over the Ansible verifier

The Ansible verifier expresses assertions as `register` / `assert`
YAML pairs — verbose and awkward for anything involving string parsing,
regex, or negative assertions. testinfra tests are ordinary pytest
functions: `host` is a fixture that connects to the converged instance,
and assertions are plain Python. Prefer testinfra for all new verify
work.

### Host fixture type

Import `Host` from `testinfra.host` for type annotations, guarded by
`TYPE_CHECKING` so it is not imported at runtime (ruff TC002):

    from __future__ import annotations

    from typing import TYPE_CHECKING, Any

    if TYPE_CHECKING:
        from testinfra.host import Host

    def test_example(host: Host) -> None:
        assert host.file("/etc/traefik").exists

All test functions must be annotated with `host: Host` and return
`-> None`. Helper functions that accept a host should use `Host` as
well. Use `from typing import Any` for YAML-parsed dict/list return
types.

### Key host fixture methods used in this role

* `host.file(path)` — inspect a file: `.exists`, `.is_directory`,
  `.mode`, `.user`, `.group`, `.content_string`
* `host.run(cmd)` — run a shell command: `.rc`, `.stdout`, `.stderr`
* `host.docker(name)` — inspect a Docker container: `.is_running`

### Installing test dependencies

    pip install -r molecule/default/requirements.txt

Contains `pytest-testinfra` and `PyYAML`.

### Test coverage approach

There is no automated coverage tool for Ansible task branches — you
build coverage by writing scenarios that exercise different variable
combinations. The `default` scenario covers the happy path with ACME
disabled. Add named scenarios under `molecule/` for:

* Preflight failure cases (bad resolver reference, uncovered FQDN)
* Multi-cert split (site FQDNs spanning two cert specs)
* `traefik_acme_enabled: true` with a mock resolver (future)

## Working with the consumer side

This role is consumed from the user's playbooks repo (not in this
repo). Inventory layout, vault structure, and the proxy host's
`traefik_sites` mapping are described in `DESIGN.md` §"Inventory
layout" and §"Migration: existing host → role-managed". When the
human asks about consumer-side changes, ask which inventory repo to
operate on — it's not in this directory tree.

## When in doubt

Read `DESIGN.md`, then ask. The schemas and decisions there came
out of a multi-round design conversation; they're load-bearing.

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
* Changes to Traefik static or dynamic configuration that affect routing,
  TLS, or service discovery

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

Infer a scope from the role layout or Traefik subsystem.

Common Ansible role scopes: `tasks`, `handlers`, `templates`,
`defaults`, `vars`, `meta`, `molecule`, `docker`, `systemd`.

Common Traefik subsystem scopes: `static-config`, `dynamic-config`,
`providers`, `entrypoints`, `routers`, `middlewares`, `services`,
`tls`, `acme`, `dashboard`, `api`, `metrics`, `tracing`, `logs`,
`plugins`.

Only include a scope when it adds clarity. Prefer the Traefik
subsystem scope for feature-driven changes (e.g., `feat(acme): ...`)
and the role-layout scope for structural changes
(e.g., `refactor(tasks): ...`).

### Step 5 — Write the commit message

Format exactly as:

    <type>[optional scope]: <short summary (<=50 chars)>

    <body wrapped at 72 characters>

    [optional footer(s)]

**Subject line rules:**

* Use **imperative mood** ("Add", "Fix", "Update", "Remove")
* Maximum **50 characters**
* Describe the **result**, not the implementation
* Prefer Traefik or Ansible terminology over generic phrasing
  (e.g., "Add ACME HTTP-01 resolver", not "Add new variable")

**Body rules** (required):

Explain **why the change was made**, focusing on:

* What deployment scenario or upstream Traefik behavior motivated it
* What downstream role consumers need to know to upgrade safely
* Any Traefik or Ansible version constraints involved

When helpful, summarize key changes using bullet points.

**Bullet rules:**

* Use `*` (asterisk) for all bullets — never `-` or `•`
* Nested bullets indented with two spaces
* No Markdown formatting of any kind

Example:

    * Add file provider configuration template
    * Wire provider into static config and reload handler
      * Triggers Traefik reload via systemd on change

**Ansible-specific expectations:**

* Call out new, renamed, or removed default variables
* Note when handler names, tag names, or public task names change
* Mention idempotency improvements when relevant
* Reference supported platforms when adding OS- or
  distribution-specific tasks
* Flag changes to `meta/main.yml` (galaxy metadata, role
  dependencies, minimum Ansible version, supported platforms)
* Note molecule scenario additions or removals

**Traefik-specific expectations:**

* Distinguish between **static configuration** (requires restart)
  and **dynamic configuration** (hot-reloaded by the file provider)
* Note the minimum Traefik version when using new directives
* Call out new providers, middlewares, routers, or entrypoints by name
* Highlight TLS or ACME changes that affect certificate issuance or
  renewal
* Mention dashboard or API exposure changes — these have security impact

### Breaking changes

A change is breaking when it:

* Renames or removes a default variable
* Renames or removes a handler, tag, or public task name
* Changes a default value in a way that alters runtime behavior
* Drops support for a Traefik or Ansible version
* Restructures generated configuration in a way consumers' overrides
  cannot accommodate
* Changes dashboard, API, or entrypoint exposure defaults

If the diff introduces a breaking change:

* Add `!` after the type/scope in the subject
* Include a footer: `BREAKING CHANGE: <description>`

Examples:

    feat(acme): add DNS-01 challenge support for Cloudflare
    fix(dynamic-config): correct middleware ref in router
    refactor(tasks): split install and configure into files
    chore(meta): bump minimum Ansible version to 2.15
    test(molecule): add scenario for Ubuntu 24.04

    feat(defaults)!: rename traefik_acme_email variable

    BREAKING CHANGE: traefik_acme_email is now
    traefik_acme_account_email; update playbook vars before upgrading.

### Step 6 — Output rules

Return **only the commit message** — no explanation, no analysis,
no diff, no markdown formatting, no code fences. The output will be
pasted directly into a git commit editor.
