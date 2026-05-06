# ansible-role-traefik — Design

## Purpose

Deploy Traefik v3 as the reverse-proxy and TLS-termination edge at each
regional office, driven by Ansible inventory rather than hand-edited
YAML on each VM. Replaces the current "ssh in, edit `config/dynamic/*.yml`,
pray" workflow.

## Goals

* One source of truth for routing per region, expressed as inventory data,
  not as duplicated YAML across portals.
* Adding a site = one entry in `host_vars`. Adding a region = one new
  inventory host. Rotating a partner's IP = one edit in a shared allowlist
  group, not five edits across five files.
* Hot-reloadable changes (routers, services, middlewares, allowlists)
  do not restart Traefik.
* TLS via Let's Encrypt **DNS-01** challenge using a per-region wildcard
  cert set. Cert issuance does not require :80 to be reachable from the
  internet, and one cert covers any number of subdomains under a
  controlled zone.
* Compatible with `ansible-core` >= 2.20, Debian 12/13 and Ubuntu 22.04/24.04,
  Traefik v3.

## Non-goals

* No multi-cluster orchestration (Swarm, Kubernetes). Each VM is a
  single-host Docker Engine running the proxy and, optionally, co-located
  application containers.
* No DNS record automation. The role talks to IONOS only for ACME TXT
  records; A/AAAA records for site FQDNs remain operator-managed.
* No external (non-ACME) cert distribution path. Importing certs from
  corp PKI / cert-manager / file is left as future work; schema reserved.
* No host-local firewall management. Perimeter filtering is handled by
  the upstream Fortigate; the role assumes :80 and :443 are reachable
  to the proxy VM from the internet (DNS-01 does not strictly require
  :80, but the entrypoint is still served for HTTP→HTTPS redirect).

---

## Current state (reference: comap.com dmz host)

One VM runs `docker compose up -d` against a hand-maintained tree:

```
traefik
├── certs/acme.json
├── compose.yml
└── config
    ├── traefik.yml              # static config
    └── dynamic/
        ├── judging-portal.yml
        ├── contest-portal.yml
        ├── joomla-portal.yml
        ├── link-portal.yml
        └── payment-portal.yml
```

Pain points observed in the live files:

* `redirect-https`, `security-headers`, the `noop` service, the catch-all
  redirect router, and the `*-transport` block are duplicated across every
  dynamic file.
* IP allowlists overlap heavily — corp office, two staff home IPs, and the
  internal dmz subnet recur with portal-specific additions layered on top.
  Each list is restated per portal.
* Per-portal `*-acme` routers exist solely to keep the ACME challenge path
  unredirected for HTTP-01 issuance. Eliminated entirely in the new
  design — DNS-01 needs no HTTP traffic for challenge, so neither the
  per-portal acme routers nor the catch-all redirect-to-https router
  carry any ACME concern.
* Container hard-codes label `com.comap.dmz.env: "devel"`, journald tag
  `traefik.dmz.comap.com`, network name `dmz`, image tag `traefik:3`.
  None of these are parameterized today.
* Drift: `payment-portal.yml` uses `redirect-https` with `permanent: false`
  while every other portal uses `permanent: true` — normalized to
  `permanent: true` org-wide in the new design. `link-portal.yml` defines
  a `minio-rfc1918-only` allowlist middleware but the HTTPS router has
  the middleware reference commented out — restored in the new design.
* Provider config enables both `docker` and `file` providers, but no
  current backend uses the docker provider. Co-located containers are a
  future-state need.

---

## Target architecture

```
                    ┌─────────────────────────────────────┐
                    │      Ansible controller             │
                    │  inventory + ansible-vault          │
                    │  ansible-role-traefik (this repo)   │
                    └────────────────┬────────────────────┘
                                     │ ssh
                ┌────────────────────┼────────────────────┐
                ▼                    ▼                    ▼
         ┌───────────┐        ┌───────────┐        ┌───────────┐
         │ Region A  │        │ Region B  │        │ Region C  │
         │ proxy VM  │        │ proxy VM  │        │ proxy VM  │
         │           │        │           │        │           │
         │ Traefik   │        │ Traefik   │        │ Traefik   │
         │ (Docker)  │        │ (Docker)  │        │ (Docker)  │
         │  + LE     │        │  + LE     │        │  + LE     │
         └─────┬─────┘        └─────┬─────┘        └─────┬─────┘
               │                    │                    │
       LAN backends + co-located containers per region
```

Each VM:

* Runs Traefik v3 in a single container managed by
  `community.docker.docker_compose_v2`.
* Joins the `traefik_proxy` Docker network (created by the role).
  Co-located application containers can attach to the same network and
  expose themselves via Traefik labels.
* Persists `acme.json` to a host-mounted directory.
* Is configured entirely from its inventory entry — no manual files on
  the VM other than what Ansible writes.

---

## Role layout

```
ansible-role-traefik/
├── defaults/main.yml          # public interface
├── meta/main.yml              # platforms, dependencies, min ansible
├── handlers/main.yml          # reload/restart hooks
├── tasks/
│   ├── main.yml               # orchestrates the rest
│   ├── preflight.yml          # assert vars, docker present, ports free
│   ├── install.yml            # dirs, render compose.yml + traefik.yml
│   ├── network.yml            # docker_network: traefik_proxy
│   ├── sites.yml              # render dynamic/sites.yml + middlewares.yml
│   ├── service.yml            # docker_compose_v2 up
│   └── verify.yml             # wait for healthcheck green
├── templates/
│   ├── compose.yml.j2
│   ├── traefik.yml.j2
│   └── dynamic/
│       ├── middlewares.yml.j2  # org-wide library + per-site allowlists
│       └── sites.yml.j2        # routers + services + serversTransports
├── vars/main.yml              # internal constants
├── molecule/default/          # CI: Debian 12, Debian 13, Ubuntu 22.04, 24.04
├── README.md
└── DESIGN.md (this file)
```

---

## Public interface (`defaults/main.yml`)

Defaults below are the role's public contract. Renames or removed
variables are breaking changes per the project's conventional-commits
rules (see `AGENTS.md`).

```yaml
# Image and runtime
traefik_image: "traefik:v3.4"           # minor-pinned; bumped intentionally
traefik_container_name: traefik
traefik_restart_policy: unless-stopped
traefik_check_new_version: true          # set false to silence the version-check log line
traefik_memory_limit: 1g
traefik_memory_reservation: 512m
traefik_ulimit_nofile_soft: 65536
traefik_ulimit_nofile_hard: 65536

# Filesystem layout on the host
traefik_data_dir: /etc/traefik
traefik_dynamic_dir: "{{ traefik_data_dir }}/dynamic"
traefik_certs_dir: /var/lib/traefik/certs
traefik_compose_dir: /opt/traefik

# Networking
traefik_docker_network: traefik_proxy
traefik_entrypoint_web_port: 80
traefik_entrypoint_websecure_port: 443
traefik_trusted_ips:
  - "127.0.0.1/32"
  - "10.0.0.0/8"
  - "172.16.0.0/12"
  - "192.168.0.0/16"

# Logging
traefik_log_level: INFO                  # DEBUG only when troubleshooting
traefik_log_format: json
traefik_journald_tag: "traefik.{{ inventory_hostname }}"
traefik_journald_labels:
  env: "{{ traefik_environment | default('prod') }}"

# ACME / Let's Encrypt — DNS-01 challenge with multiple DNS providers
traefik_acme_enabled: true
traefik_acme_email: ""                   # required when acme_enabled
traefik_acme_caserver: ""                # set to LE staging during testing

# Default DNS resolvers used to verify TXT propagation. Each resolver
# entry below can override.
traefik_acme_default_dns_resolvers:
  - "1.1.1.1:53"
  - "8.8.8.8:53"

# Resolver definitions — one entry per (LE account, DNS provider) pair.
# Each resolver gets its own acme.json file under traefik_certs_dir
# (acme-<name>.json). Provider credentials are passed to the container
# via env vars whose names match what the lego provider expects.
# Defaults below are sensible per-provider starting points; tune per
# deployment via group_vars.
traefik_acme_resolvers:
  ionos:
    provider: ionos
    delay_before_check: 120              # IONOS propagation is very slow
    env:
      IONOS_API_KEY: "{{ traefik_ionos_api_key }}"
  route53:
    provider: route53
    delay_before_check: 0
    env:
      AWS_ACCESS_KEY_ID: "{{ traefik_route53_access_key_id }}"
      AWS_SECRET_ACCESS_KEY: "{{ traefik_route53_secret_access_key }}"
      AWS_REGION: us-east-1              # Route53 is global; lego still wants a region
  cloudflare:
    provider: cloudflare
    delay_before_check: 0
    env:
      CF_DNS_API_TOKEN: "{{ traefik_cloudflare_api_token }}"

# DNS provider credentials — MUST be vaulted; never set in defaults.
# Only populate the ones you actually use; unused resolvers can stay
# defined here at zero cost (Traefik only contacts a resolver when a
# cert references it).
traefik_ionos_api_key: ""
traefik_route53_access_key_id: ""
traefik_route53_secret_access_key: ""
traefik_cloudflare_api_token: ""

# Wildcard certs and the default cert (see Schemas).
traefik_wildcard_certs: []
traefik_default_cert: ""                 # name of an entry in
                                         # traefik_wildcard_certs

# Providers
traefik_provider_docker_enabled: true
traefik_provider_docker_exposed_by_default: false
traefik_provider_file_enabled: true

# Routing data (typically set in host_vars)
traefik_sites: []
traefik_allowlist_groups: {}
traefik_default_servers_transport:
  forwardingTimeouts:
    dialTimeout: 10s
    responseHeaderTimeout: 300s
    idleConnTimeout: 300s
  maxIdleConnsPerHost: 200

# Verification
traefik_verify_healthcheck: true
traefik_verify_healthcheck_timeout: 60   # seconds
```

---

## Schemas

### `traefik_sites`

A list of site dicts. Each dict produces one HTTPS router, one service,
and (if `allowlist` is non-empty) one ipAllowList middleware in the
generated `dynamic/sites.yml`.

```yaml
traefik_sites:
  - name: judging-portal              # required; used as router/service id
    fqdns:                            # required; one or more hostnames
      - judging-portal.dev.comap.com
      - judging.portal.comap.com
      - judging.portal.comap.org
    backend: http://10.78.1.247:8000  # required; full URL
    backend_tls_skip_verify: false    # optional, default false
    cert: comap-com                   # optional; name from
                                      # traefik_wildcard_certs. Defaults
                                      # to traefik_default_cert.
    allowlist:                        # optional; references group names
      - corp_office
      - staff_home
      - dmz_internal
      - judging_extra
    extra_middlewares: []             # optional; appended after allowlist
    pass_host_header: true            # optional, default true
    servers_transport: null           # optional override; null = default
    priority: null                    # optional router priority override
```

Notes:

* `security-headers` is applied automatically to every site via
  `traefik_default_middlewares` (see below). Omit from per-site
  `extra_middlewares` unless you want it twice.
* Cert resolution: for each FQDN, the role finds the cert spec from
  `traefik_wildcard_certs` whose `main` or `sans` covers it. If
  `cert:` is set on the site, every FQDN must fall under that cert;
  preflight fails otherwise. If `cert:` is unset, FQDNs are grouped
  by their best-covering cert and the site emits one router per
  group (see `traefik_wildcard_certs` notes for the multi-cert split
  rule).

### `traefik_allowlist_groups`

A dict of named CIDR lists. Sites reference groups by name; the role
unions referenced groups to produce a per-site `ipAllowList` middleware.

```yaml
traefik_allowlist_groups:
  corp_office:
    - "50.187.180.96/28"            # COMAP HQ public
  staff_home:
    - "68.47.4.109/32"              # Bob (review 2026-Jan)
    - "24.63.40.131/32"             # John (review 2026-Jan)
  dmz_internal:
    - "192.168.100.0/24"
  vpn:
    - "10.78.1.253/32"
  judging_extra:
    - "54.241.1.111/32"             # judging-portal
    - "54.153.24.64/32"             # gold-image-judging-portal
  contest_extra:
    - "52.38.114.194/32"            # contest.com.com
```

Comments next to each CIDR are preserved through templating (Jinja can
emit them) so the per-IP review-date metadata isn't lost.

### `traefik_wildcard_certs`

A list of LE certificates to issue and renew. Each entry binds to a
named resolver from `traefik_acme_resolvers` and produces one ACME
order against that resolver's DNS provider. Every router whose FQDNs
fall under this entry's `main` + `sans` reuses the same cert.

```yaml
traefik_wildcard_certs:
  - name: comap-com                # internal id; referenced by sites
    resolver: ionos                # zones for these domains live at IONOS
    main: "*.portal.comap.com"
    sans:
      - "*.dev.comap.com"
      - "www.link.comap.com"
  - name: comap-org
    resolver: route53              # *.comap.org zone is at AWS Route53
    main: "*.portal.comap.org"
    sans: []

traefik_default_cert: comap-com    # cert installed in TLS default store
```

Notes:

* **All domains in a single cert spec must live in zones the bound
  resolver's DNS provider controls.** A cert can't span IONOS and
  Route53 (lego doesn't multi-provider one challenge), so registered
  domains hosted at different providers need separate cert specs.
* The cert named in `traefik_default_cert` is installed in the default
  TLS store. Routers that don't pin a `cert:` get this one — useful for
  co-located docker-labeled containers that don't need to know cert
  names.
* A site whose `fqdns` span multiple registered domains (and therefore
  multiple cert specs) is split internally into one router per cert —
  same backend, same middleware chain, same allowlist. The split is
  invisible at the inventory level; the operator still writes one
  site entry. Naming convention: `<site.name>-<cert.name>` for the
  generated routers.
* Adding a new wildcard scope = one entry here + a re-run. ACME order
  happens once; subsequent runs are no-ops while the cert is valid.

### Org-wide middleware library

Defined as constants in `vars/main.yml` and rendered into
`dynamic/middlewares.yml`:

* `security-headers` — HSTS 2y + subdomains, frameDeny,
  contentTypeNosniff, referrer same-origin.
* `compress` — gzip/brotli on text responses.
* (extensible — add to `traefik_extra_middlewares` to emit additional
  shared middlewares.)

`traefik_default_middlewares` lists which library middlewares are
applied to every site (default: `[security-headers]`).

---

## Static config (`traefik.yml.j2`)

Replaces the current 85-line static config with a smaller one.
Notable differences from today:

* `entryPoints.web.http.redirections` performs the HTTP→HTTPS redirect
  at the entrypoint. With DNS-01 there is no challenge traffic on :80
  to preserve, so the catch-all `redirect-to-https` router and every
  per-portal `*-acme` router go away entirely.
* `certificatesResolvers` is rendered as one block per entry in
  `traefik_acme_resolvers` — each with its own `dnsChallenge.provider`,
  `delayBeforeCheck`, propagation `resolvers` list, and a per-resolver
  `storage` path (`{{ traefik_certs_dir }}/acme-<name>.json`). No
  `httpChallenge` block.
* `forwardedHeaders.trustedIPs` driven by `traefik_trusted_ips`.
* `providers.docker.network: "{{ traefik_docker_network }}"` and
  `exposedByDefault: false` per role default.
* `providers.file.directory: {{ traefik_dynamic_dir }}` with
  `watch: true` for hot-reload.
* `accessLog` defaults preserved (json, drop sensitive headers).
* `log.level` defaults to `INFO`, not `DEBUG`. Override per-host when
  troubleshooting.

---

## Dynamic config

Three files generated per host, all atomic-written to
`{{ traefik_dynamic_dir }}/`:

* `middlewares.yml` — org-wide library (`security-headers`, etc.) plus
  one `<site-name>-allowlist` middleware per site that has a non-empty
  `allowlist`. Allowlists are rendered as the union of the referenced
  groups, deduped, with original comments preserved.
* `sites.yml` — one router (websecure entrypoint) and one service per
  site, plus shared `serversTransports`. Each router's `tls` block
  carries the `domains` list from the referenced cert spec, which
  triggers issuance/reuse of the matching wildcard cert.
* `tls.yml` — declares the TLS default store backed by
  `traefik_default_cert`, plus org-wide `tls.options` (modern profile:
  TLS 1.2+/1.3, restricted cipher suites). Sites do not need to
  reference these — the store is implicit.

Per-site middleware chain (in order): `<site>-allowlist` (if present),
then `traefik_default_middlewares`, then `extra_middlewares`.

Templates use atomic write + Traefik's `watch: true` file provider,
so a config change reloads routes without restarting the container.
Adding a new wildcard scope to `traefik_wildcard_certs` also reloads;
the resolver issues the cert in the background once a router references
the new domain set.

---

## TLS / ACME

Multiple ACME resolvers, all backed by Let's Encrypt, each bound to a
different DNS provider via lego. Built-in support for **IONOS**,
**AWS Route53**, and **CloudFlare**; any other lego DNS provider can
be added by appending an entry to `traefik_acme_resolvers`. Each
wildcard cert spec names its resolver, so one host can serve cert sets
issued by different providers concurrently.

Provider configuration (rendered into static config, one block per
resolver):

```yaml
certificatesResolvers:
  ionos:
    acme:
      email: "{{ traefik_acme_email }}"
      storage: "{{ traefik_certs_dir }}/acme-ionos.json"
      {% if traefik_acme_caserver %}caServer: "{{ traefik_acme_caserver }}"{% endif %}
      dnsChallenge:
        provider: ionos
        delayBeforeCheck: 120
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
  route53:
    acme:
      email: "{{ traefik_acme_email }}"
      storage: "{{ traefik_certs_dir }}/acme-route53.json"
      {% if traefik_acme_caserver %}caServer: "{{ traefik_acme_caserver }}"{% endif %}
      dnsChallenge:
        provider: route53
        delayBeforeCheck: 0
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
  cloudflare:
    acme:
      email: "{{ traefik_acme_email }}"
      storage: "{{ traefik_certs_dir }}/acme-cloudflare.json"
      {% if traefik_acme_caserver %}caServer: "{{ traefik_acme_caserver }}"{% endif %}
      dnsChallenge:
        provider: cloudflare
        delayBeforeCheck: 0
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
```

Credentials:

* lego reads provider credentials from environment variables. The
  role assembles a single `.env.secrets` file (`0600` root-owned) at
  `{{ traefik_compose_dir }}/.env.secrets` containing every env entry
  from every defined resolver, and the compose `env_file:` references
  it. Compose YAML never contains secrets directly.
* Per-provider env keys (lego conventions):
  * IONOS — `IONOS_API_KEY`
  * Route53 — `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
    `AWS_REGION`. IAM permissions: `route53:GetChange`,
    `route53:ChangeResourceRecordSets`,
    `route53:ListHostedZonesByName`. Scope the key to the specific
    hosted zone via an IAM policy condition.
  * CloudFlare — `CF_DNS_API_TOKEN` (scoped token; preferred over
    the older `CF_API_EMAIL` + `CF_API_KEY` global key path).
* All credentials have DNS-zone write scope on at least one zone.
  Treat as high-blast-radius: vaulted vars file per controller,
  preflight uses `no_log: true` when asserting presence.

IONOS-specific tuning:

* `delay_before_check: 120` is the role default. IONOS's authoritative
  servers can lag 60–120 s behind a TXT update from their API. Setting
  this lower causes "no DNS record found" challenge failures and burns
  LE issuance attempts. If observed propagation is consistently
  faster, dial it down per host or per resolver.
* `traefik_acme_default_dns_resolvers` (1.1.1.1 / 8.8.8.8) is what
  Traefik uses to *check* propagation. These ignore IONOS's caches,
  so propagation has to reach the public DNS edge before the check
  passes — which is exactly why the delay is necessary.

Storage and lifecycle:

* One `acme-<resolver>.json` file per resolver under
  `traefik_certs_dir` (`0600`, root-owned), each bind-mounted into the
  container. Per-file isolation makes per-resolver backup trivial and
  contains the blast radius if one is corrupted.
* Renewal: Traefik handles automatically when certs are within ~30
  days of expiry. No cron / systemd timer required.
* Email: `traefik_acme_email` is required when ACME is enabled;
  preflight asserts. Same email is used for every resolver's LE
  account.
* Staging: set `traefik_acme_caserver` to LE's staging URL during
  initial bring-up — applies to every resolver. Once happy, clear the
  variable, delete every `acme-*.json` once, re-run to obtain prod
  certs.

Operational properties of the DNS-01 switch:

* **No port-80 reachability needed for issuance.** Sites can be
  brought up before public DNS A/AAAA records exist; certs issue
  against the DNS challenge without inbound traffic.
* **Wildcard certs simplify SAN drift.** Adding a new subdomain
  doesn't trigger a new ACME order; the existing wildcard already
  covers it.
* **Renewal traffic is outbound only** (HTTPS to each DNS provider's
  API + LE). Eliminates a class of "cert renewal failed because :80
  was blocked" incidents.
* **Trade-off**: dependency on each enabled DNS provider's API
  availability during issuance and renewal. If a provider is down at
  renewal time, that resolver's existing certs remain valid until
  expiry; certs from other resolvers are unaffected.

Credential rotation policy:

* **IONOS**: rotate on suspicion only (suspected leak, staff
  departure with knowledge, audit finding). No scheduled cadence.
  Procedure: edit vaulted var, re-run role; new key is in effect on
  the next renewal cycle without restart.
* Route53 / CloudFlare: same policy unless a higher-up control
  (org IAM rotation policy, key-management compliance requirement)
  dictates otherwise.

Backup of `acme-*.json` files: out of scope for this role. Recommended
a separate role / cron copy off-box daily; with wildcards in play, one
file may cover many sites and losing it triggers LE rate limits.

---

## Docker provider — co-located containers

The role enables `providers.docker` with `exposedByDefault: false` and
network `traefik_proxy`. Co-located application containers opt in by
attaching to the network and declaring labels in their own compose
files. The role does **not** generate labels for application services;
each app's compose owns its labels.

Because the TLS default store is backed by a wildcard cert, labeled
containers serving an FQDN under that wildcard need *zero* cert
plumbing in their labels — `tls=true` is enough. Containers serving
FQDNs under a non-default wildcard pin via `tls.domains[0].main`.

Conventions documented in README:

```yaml
# example app compose.yml — FQDN under the default wildcard
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

For an FQDN under a non-default wildcard (e.g. the .org one), pin the
cert spec on the router:

```yaml
labels:
  traefik.http.routers.myapp.tls.certresolver: "letsencrypt"
  traefik.http.routers.myapp.tls.domains[0].main: "*.portal.comap.org"
```

Allowlist middlewares defined in `dynamic/middlewares.yml` are
referenceable from labeled containers via the `@file` provider suffix
(e.g. `corp_office-allowlist@file`). This lets co-located containers
reuse the same allowlist groups as file-provider sites.

---

## Bootstrap & lifecycle

The role assumes Docker Engine and the docker SDK for Python are
already installed on the target. `meta/main.yml` declares a soft
dependency on `geerlingguy.docker` (or equivalent) so a fresh VM is
one playbook run end-to-end if the consumer wants it.

`tasks/main.yml` order:

1. `preflight.yml` — assert required vars present (`traefik_acme_email`
   when ACME enabled; for every cert, the bound resolver exists in
   `traefik_acme_resolvers` and that resolver's env vars all resolve
   to non-empty values; non-empty `traefik_sites`; every site's FQDNs
   covered by at least one cert; `traefik_default_cert` names a real
   entry), check Docker socket reachable. Cred checks use
   `no_log: true`.
2. `install.yml` — create directories, render `compose.yml`,
   `traefik.yml`, write `.env.secrets` (`0600`) with the env vars
   for every defined resolver.
3. `network.yml` — create `traefik_proxy` Docker network.
4. `sites.yml` — render `dynamic/middlewares.yml`, `dynamic/sites.yml`,
   `dynamic/tls.yml`. Notify a no-op handler (file provider
   hot-reloads on its own; restart only if `traefik.yml` changed).
5. `service.yml` — `docker_compose_v2 up` against rendered compose.
6. `verify.yml` — poll `docker inspect` until healthcheck reports
   `healthy`, fail after timeout.

Handlers:

* `restart traefik` — triggered only by changes to `compose.yml` or
  `traefik.yml` (static config). Dynamic changes never restart.

Healthcheck baked into `compose.yml`:

```yaml
healthcheck:
  test: ["CMD", "traefik", "healthcheck", "--ping"]
  interval: 10s
  timeout: 3s
  retries: 5
  start_period: 30s
```

Requires `ping:` enabled in static config (added by the template when
`traefik_verify_healthcheck` is true).

---

## Inventory layout (consumer-side example)

```
inventory/
├── group_vars/
│   ├── all/
│   │   ├── traefik.yml          # org-wide defaults, allowlist groups
│   │   └── vault_traefik.yml    # ansible-vault: ACME email if private
│   └── traefik_proxies.yml      # traefik_acme_email, image pin, etc.
├── host_vars/
│   ├── proxy-comap-dmz-01.yml   # current comap host, restated as data
│   ├── proxy-uswest-01.yml
│   └── proxy-euwest-01.yml
└── hosts.yml
```

`group_vars/all/traefik.yml` defines `traefik_allowlist_groups`,
`traefik_wildcard_certs`, `traefik_default_cert`, and any org-wide
overrides. `vault_traefik.yml` holds DNS provider credentials —
`traefik_ionos_api_key`, `traefik_route53_access_key_id` /
`traefik_route53_secret_access_key`, `traefik_cloudflare_api_token` —
plus `traefik_acme_email` if you want it private. Only the credentials
for resolvers actually referenced by a cert need to be populated; the
others can stay empty. Each `host_vars/proxy-*.yml` contains
`traefik_sites` for that VM and may override the default cert when the
VM serves only non-default domains.

---

## Migration: comap dmz host → role-managed

Strategy: stand the role-managed deploy up on a fresh path
(`/opt/traefik`) without touching the existing `./traefik` tree. The
existing setup uses HTTP-01 per-FQDN certs; the new setup uses DNS-01
wildcards, so a fresh `acme.json` is required (the old one's per-FQDN
certs aren't reused). Validate against LE staging first.

Step-by-step:

1. Provision DNS-API credentials and store in
   `group_vars/all/vault_traefik.yml`:
   * `traefik_ionos_api_key` — IONOS API key with write scope on the
     `comap.com` zone.
   * `traefik_route53_access_key_id` / `traefik_route53_secret_access_key`
     — IAM user credentials scoped to the `comap.org` Route53 hosted
     zone (permissions: `route53:GetChange`,
     `route53:ChangeResourceRecordSets`,
     `route53:ListHostedZonesByName`).
2. Add `proxy-comap-dmz-01` to inventory; populate `traefik_sites`
   from the table below and set `traefik_wildcard_certs` /
   `traefik_default_cert` per the layout below. Set
   `traefik_acme_email: techs@real-time.com` and
   `traefik_acme_caserver` to LE staging.
3. Run the role. Verify: container healthcheck green, both
   `acme-ionos.json` and `acme-route53.json` populated with their
   respective wildcards, each site responds with the expected
   (staging) cert chain. The IONOS resolver may take 1–3 minutes per
   issuance attempt due to `delay_before_check: 120`.
4. Cross-check generated routes against the existing tree. Two
   intentional changes from current behavior: `link-portal` regains
   its allowlist (was commented out), and `payment-portal`'s redirect
   becomes `permanent: true` (was `permanent: false`).
5. Clear `traefik_acme_caserver`, delete the staging `acme-*.json`
   files once, re-run to issue prod certs against LE production.
6. Stop the old stack (`docker compose down` in `./traefik`).

Wildcard cert layout for the comap host. `comap.com` zones are at
IONOS, `comap.org` is at Route53, so two cert specs bound to two
resolvers:

```yaml
traefik_wildcard_certs:
  - name: comap-com
    resolver: ionos
    main: "*.portal.comap.com"
    sans:
      - "*.dev.comap.com"
      - "www.link.comap.com"
  - name: comap-org
    resolver: route53
    main: "*.portal.comap.org"
    sans: []

traefik_default_cert: comap-com
```

Three of the five portals (`judging-portal`, `contest-portal`,
`joomla-portal`) currently serve both `.com` and `.org` FQDNs. Under
this layout each of those sites emits two routers under the hood —
`<site>-comap-com` (issued via IONOS) and `<site>-comap-org` (issued
via Route53) — sharing the same backend, middleware chain, and
allowlist. The split is invisible at the inventory level (still one
entry per site).

Mapping of today's portals to `traefik_sites`:

| name           | fqdns                                                                            | backend                  | allowlist groups                                              |
|----------------|----------------------------------------------------------------------------------|--------------------------|---------------------------------------------------------------|
| judging-portal | judging-portal.dev.comap.com, judging.portal.comap.com, judging.portal.comap.org | http://10.78.1.247:8000  | corp_office, staff_home, dmz_internal, judging_extra          |
| contest-portal | contest.portal.comap.com, contest.portal.comap.org                               | http://10.78.1.246:80    | corp_office, staff_home, dmz_internal                         |
| joomla-portal  | joomla.portal.comap.com, joomla.portal.comap.org                                 | http://10.78.1.249:80    | corp_office, staff_home, dmz_internal                         |
| link-portal    | link.portal.comap.com, www.link.comap.com                                        | http://10.78.1.243:9000  | corp_office, staff_home, dmz_internal, vpn, contest_extra     |
| payment-portal | payment-portal.dev.comap.com, payment.portal.comap.com                           | http://10.78.1.245:8000  | corp_office, staff_home, dmz_internal, contest_extra          |

---

## Open questions

* **Backup of acme-*.json** — out of scope for this role. With
  wildcard certs the blast radius of losing one is bigger (one
  wildcard covers many sites). Decide which role / cron job owns the
  backup. Per-resolver files mean a per-provider RPO is achievable
  if useful.
* **Multi-region rollout order** — pick the first non-comap region to
  pilot; comap dmz cuts over after the role is proven elsewhere. New
  regions need their own credentials scoped to that region's zones
  (or shared org credentials with zone-level write to the relevant
  zones).
* **IONOS `delay_before_check` measurement** — 120 s is a defensive
  default. After the role is in production, capture actual TXT
  propagation lag from a few issuance/renewal cycles and tune down
  if measurements consistently show faster propagation. Each saved
  second is shaved off every renewal.

## Future work (not built now)

* **Drop the `traefik_sites | length > 0` preflight assertion.** As
  more co-located containers adopt Docker labels for self-registration,
  `traefik_sites` will shrink toward empty. An empty list is a valid
  deployment when all routing is handled by the Docker provider. The
  assertion should be removed (or guarded by a
  `traefik_require_sites: true` variable) before any host reaches that
  state, or the role will refuse to converge on a legitimately correct
  configuration.

* External cert source (corp PKI, cert-manager output, manual import).
  Schema reserved: `traefik_tls_store` dict supplying cert+key bytes,
  with per-site `cert:` override pointing at a store entry instead of
  an ACME-issued spec. Mostly relevant if a site needs an EV / OV
  cert that LE can't issue.
* Additional lego DNS providers as needed (e.g. Azure DNS, Google
  Cloud DNS, GoDaddy). Add an entry to `traefik_acme_resolvers` with
  the provider's name and env-var mapping; no role change required if
  the provider is supported by the lego version Traefik ships.
* AWS IAM-via-instance-profile / IRSA for Route53 — drops the static
  AWS keys from vault if the proxy VMs run on EC2.
* Traefik dashboard / API exposure with authentication middleware
  (currently not exposed at all).
* Metrics export (Prometheus endpoint, OpenTelemetry tracing).
* Backup automation for `acme-*.json`.
