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
  - name: comap-com
    resolver: ionos
    main: "*.portal.comap.com"
    sans:
      - "*.dev.comap.com"
  - name: comap-org
    resolver: route53
    main: "*.portal.comap.org"
    sans: []

traefik_default_cert: comap-com    # installed in the TLS default store
```

### Sites

Set in `host_vars` — one list per proxy host.

```yaml
traefik_sites:
  - name: judging-portal
    fqdns:
      - judging-portal.dev.comap.com
      - judging.portal.comap.com
    backend: http://10.78.1.247:8000
    backend_tls_skip_verify: false     # default
    cert: comap-com                    # optional; defaults to traefik_default_cert
    allowlist:                         # optional; references traefik_allowlist_groups
      - corp_office
      - staff_home
    extra_middlewares: []              # optional; appended after allowlist
    pass_host_header: true             # default
```

### Allowlist groups

Org-wide named CIDR sets. Sites compose by reference; the role unions
and deduplicates referenced groups per site.

```yaml
traefik_allowlist_groups:
  corp_office:
    - "50.187.180.96/28"
  staff_home:
    - "68.47.4.109/32"
  dmz_internal:
    - "192.168.100.0/24"
```

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
      traefik.http.routers.myapp.rule: "Host(`myapp.portal.comap.com`)"
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
  traefik.http.routers.myapp.tls.domains[0].main: "*.portal.comap.org"
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
