# Claude Code project notes — ansible-role-traefik

This is an Ansible role that deploys Traefik v3 as a reverse proxy /
TLS edge at regional offices. Forked from arillso/ansible.traefik
(itself a fork of sbaerlocher/ansible.traefik), being modernized for
`ansible-core` 2.20, Traefik v3, Debian 12/13, Ubuntu 22.04/24.04,
and a multi-region deployment model.

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

This is a breaking change to the role's public interface. Per
`AGENTS.md`, breaking-change commits get the `!` marker and a
`BREAKING CHANGE:` footer.

## Conventions

* **Commits**: follow `AGENTS.md` exactly. Conventional Commits,
  imperative mood, bodies wrapped at 72, asterisk bullets.
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
