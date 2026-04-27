# Ansible Role: traefik

[![CI](https://github.com/basictheprogram/ansible-role-traefik/actions/workflows/ci.yml/badge.svg)](https://github.com/basictheprogram/ansible-role-traefik/actions/workflows/ci.yml)
[![Ansible Galaxy](https://img.shields.io/badge/ansible--galaxy-traefik-blue.svg?style=popout-square)](https://galaxy.ansible.com/realtime/traefik)
[![Ansible Role](https://img.shields.io/ansible/role/d/realtime/traefik.svg?style=popout-square)](https://galaxy.ansible.com/realtime/traefik)

Deploys [Traefik v3](https://doc.traefik.io/traefik/) as a reverse proxy and
TLS edge on a single Docker host. DNS-01 ACME (IONOS, Route53, Cloudflare),
wildcard certs, and file-provider dynamic config are the primary use case.

> For full architecture, schemas, and design decisions see [DESIGN.md](DESIGN.md).

## Requirements

- ansible-core >= 2.20
- Docker Engine and the `docker` Python SDK on the target host
  (soft dependency: `geerlingguy.docker`)
- `community.docker` collection >= 3.0

## Installation

```bash
ansible-galaxy install realtime.traefik
```

Or pin to this repository in `requirements.yml`:

```yaml
roles:
  - name: realtime.traefik
    src: https://github.com/basictheprogram/ansible-role-traefik
    version: main
```

## Role Variables

All variables with their defaults live in `defaults/main.yml`. The key
ones to set in `host_vars` or `group_vars` are listed below.

### ACME / TLS

```yaml
traefik_acme_enabled: true
traefik_acme_email: "ops@example.com"      # required when ACME enabled
traefik_acme_caserver: ""                  # set to LE staging during bring-up

# One entry per (LE account, DNS provider) pair. Credentials are written
# to .env.secrets (0600) and never appear in YAML.
traefik_acme_resolvers:
  ionos:
    provider: ionos
    delay_before_check: 120
    env:
      IONOS_API_KEY: "{{ traefik_ionos_api_key }}"   # vault this
  route53:
    provider: route53
    delay_before_check: 0
    env:
      AWS_ACCESS_KEY_ID: "{{ traefik_route53_access_key_id }}"
      AWS_SECRET_ACCESS_KEY: "{{ traefik_route53_secret_access_key }}"
      AWS_REGION: us-east-1
  cloudflare:
    provider: cloudflare
    delay_before_check: 0
    env:
      CF_DNS_API_TOKEN: "{{ traefik_cloudflare_api_token }}"

# Wildcard certs — one entry per cert, bound to a resolver.
# Every router whose FQDNs fall under main/sans reuses the same cert.
traefik_wildcard_certs:
  - name: example-com
    resolver: ionos
    main: "*.portal.example.com"
    sans:
      - "*.dev.example.com"
  - name: example-org
    resolver: route53
    main: "*.portal.example.org"
    sans: []

traefik_default_cert: example-com    # installed in the TLS default store
```

#### DNS provider credentials

Credentials referenced by `traefik_acme_resolvers` must be vaulted on
the consumer side. The role reads them from these variables (only the
ones whose resolvers are actually used by a cert need to be set):

| Variable | Used by | Notes |
| :--- | :--- | :--- |
| `traefik_ionos_api_key` | IONOS resolver | DNS-zone write scope. |
| `traefik_route53_access_key_id`, `traefik_route53_secret_access_key` | Route53 resolver | IAM permissions: `route53:GetChange`, `route53:ChangeResourceRecordSets`, `route53:ListHostedZonesByName`. Scope to the relevant hosted zone. |
| `traefik_cloudflare_api_token` | Cloudflare resolver | Scoped API token — preferred over the legacy `CF_API_KEY` global key. |

The role assembles every resolver's env vars into a single `0600`,
root-owned `{{ traefik_compose_dir }}/.env.secrets` file and references
it from compose with `env_file:`. Compose YAML never contains secrets
directly. Tasks that touch credentials run with `no_log: true`.

#### LE staging during initial bring-up

For a first run, point at Let's Encrypt staging so failed challenges
don't burn production rate limits:

```yaml
traefik_acme_caserver: "https://acme-staging-v02.api.letsencrypt.org/directory"
```

Confirm the resolver writes its `acme-<name>.json` and the staging
chain reaches each FQDN, then clear `traefik_acme_caserver`, delete
every `{{ traefik_certs_dir }}/acme-*.json` once, and re-run to issue
production certs.

### Sites

Set in `host_vars` — one list per proxy host. Each entry produces one
HTTPS router on the `websecure` entrypoint, one service, and (if
`allowlist` is non-empty) one `ipAllowList` middleware named
`<name>-allowlist`.

```yaml
traefik_sites:
  - name: my-app
    fqdns:
      - my-app.dev.example.com
      - my-app.portal.example.com
    backend: http://10.0.0.10:8000
    backend_tls_skip_verify: false     # default
    cert: example-com                  # optional; defaults to traefik_default_cert
    allowlist:                         # optional; references traefik_allowlist_groups
      - corp_office
      - staff_home
    extra_middlewares: []              # optional; appended after allowlist
    pass_host_header: true             # default
    servers_transport: null            # optional override; null = role default
    priority: null                     # optional router priority override
```

#### Per-site fields

| Field | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `name` | yes | — | Used as the router/service id. Must be unique within `traefik_sites`. |
| `fqdns` | yes | — | One or more hostnames Traefik will route to this backend. Each must fall under one of the configured `traefik_wildcard_certs`. |
| `backend` | yes | — | Full upstream URL (`http://host:port` or `https://host:port`). |
| `backend_tls_skip_verify` | no | `false` | When `backend` is `https://`, set `true` to skip TLS verification of the upstream cert (self-signed backend, internal CA Traefik doesn't trust, or hostname mismatch). Ignored for `http://` backends. Maps to `serversTransport.insecureSkipVerify`. Skipping verification removes MitM protection on the proxy-to-backend hop — prefer fixing the cert chain on real networks. |
| `cert` | no | `traefik_default_cert` | Name of an entry in `traefik_wildcard_certs`. If set, every FQDN must fall under that cert (preflight fails otherwise). |
| `allowlist` | no | `[]` | List of names from `traefik_allowlist_groups`. The role unions and dedupes the referenced groups into a single `<name>-allowlist` middleware. |
| `extra_middlewares` | no | `[]` | Extra middleware names appended after the allowlist and the role's default middlewares. Reference file-provider middlewares with the `@file` suffix. |
| `pass_host_header` | no | `true` | Forward the original `Host` header to the backend (Traefik default). Set `false` only when the backend insists on receiving its own internal hostname. |
| `servers_transport` | no | `null` | Override the default `serversTransport` for this service. `null` uses `traefik_default_servers_transport`. |
| `priority` | no | `null` | Router priority override. Useful when overlapping `Host(...)` rules need a deterministic match order. |

The middleware chain on each generated router is, in order:
`<name>-allowlist` (when present), then `traefik_default_middlewares`
(default `[security-headers]`), then `extra_middlewares`. Don't
re-list `security-headers` in `extra_middlewares` unless you actually
want it twice.

### Allowlist groups

Org-wide named CIDR sets. Sites compose by reference; the role unions
and deduplicates referenced groups per site.

```yaml
traefik_allowlist_groups:
  corp_office:
    - "51.188.181.97/28"
  staff_home:
    - "69.48.14.119/32"
  dmz_internal:
    - "192.168.100.0/24"
```

YAML comments next to each CIDR survive templating, so per-IP review
metadata (owner, review date) isn't lost when the middleware is
generated.

### Default middlewares

`vars/main.yml` defines an org-wide middleware library that is rendered
into `dynamic/middlewares.yml` on every host:

- `security-headers` — HSTS (2 years, includeSubdomains, preload),
  `frameDeny`, `contentTypeNosniff`, `referrerPolicy: same-origin`.
- `compress` — gzip/brotli compression on text responses.

`traefik_default_middlewares` (default: `[security-headers]`) is
applied automatically to every site. To add an extra org-wide
middleware to all sites, prepend it to that list rather than copying
it into every site's `extra_middlewares`.

### Multi-cert behavior

When a site's `fqdns` span multiple entries in `traefik_wildcard_certs`
(for example, one FQDN under `*.example.com` and another under
`*.example.org`), the role transparently splits the site into one
router per cert — `<site>-<cert>`-named, sharing the same backend,
middleware chain, and allowlist. You still write one site entry; the
split is invisible at the inventory level.

Pin `cert:` on a site only when every FQDN demonstrably falls under
that one cert. Preflight fails otherwise.

### Bootstrap and verification

`tasks/main.yml` runs the role in this order:

1. `preflight.yml` — assert required vars (ACME email when ACME is
   enabled, every cert's resolver exists with non-empty credentials,
   `traefik_default_cert` names a real entry, every site FQDN is
   covered by at least one cert), confirm the Docker socket is
   reachable.
2. `install.yml` — create directories, render `compose.yml` and
   `traefik.yml`, write `.env.secrets`.
3. `network.yml` — create the `traefik_proxy` Docker network.
4. `sites.yml` — render `dynamic/middlewares.yml`, `dynamic/sites.yml`,
   `dynamic/tls.yml`. Traefik's file provider hot-reloads these; only
   `traefik.yml` or `compose.yml` changes trigger a container restart.
5. `service.yml` — `community.docker.docker_compose_v2` brings the
   stack up.
6. `verify.yml` — poll `docker inspect` until the container's
   healthcheck reports `healthy`, fail after
   `traefik_verify_healthcheck_timeout` seconds. The healthcheck
   itself runs `traefik healthcheck --ping` inside the container.

### Other frequently used variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `traefik_image` | `traefik:v3.4` | Docker image to pull |
| `traefik_container_name` | `traefik` | Container name |
| `traefik_memory_limit` | `1g` | Hard memory cap |
| `traefik_data_dir` | `/etc/traefik` | Static config and dynamic dir root |
| `traefik_certs_dir` | `/var/lib/traefik/certs` | ACME JSON storage |
| `traefik_compose_dir` | `/opt/traefik` | compose.yml and .env.secrets |
| `traefik_docker_network` | `traefik_proxy` | Docker network created by the role |
| `traefik_log_level` | `INFO` | Traefik log level |
| `traefik_verify_healthcheck` | `true` | Wait for container healthcheck after start |
| `traefik_verify_healthcheck_timeout` | `60` | Seconds to wait before failing |

## Co-located containers (Docker label convention)

Containers whose FQDNs fall under the default wildcard need only basic labels:

```yaml
# app compose.yml
services:
  myapp:
    image: ghcr.io/example/myapp:1.2.3
    networks: [traefik_proxy]
    labels:
      traefik.enable: "true"
      traefik.http.routers.myapp.rule: "Host(`myapp.portal.example.com`)"
      traefik.http.routers.myapp.entrypoints: "websecure"
      traefik.http.routers.myapp.tls: "true"
      traefik.http.routers.myapp.middlewares: "security-headers@file"
      traefik.http.services.myapp.loadbalancer.server.port: "8080"

networks:
  traefik_proxy:
    external: true
```

For a non-default wildcard, pin the cert on the router:

```yaml
labels:
  traefik.http.routers.myapp.tls.domains[0].main: "*.portal.example.org"
```

Allowlist middlewares are referenceable by name with the `@file` suffix:

```yaml
traefik.http.routers.myapp.middlewares: "security-headers@file,corp_office-allowlist@file"
```

## Fork history

Forked from [arillso/ansible.traefik](https://github.com/arillso/ansible.traefik)
(itself a fork of [sbaerlocher/ansible.traefik](https://github.com/sbaerlocher/ansible.traefik)).
**This role does not preserve the upstream public interface** — all
`traefik_qs_*` and `traefik_confkey_*` variables are removed. See the
breaking-change commit log for details.
