# Ansible Role: traefik

[![CI](https://github.com/basictheprogram/ansible-role-traefik/actions/workflows/ci.yml/badge.svg)](https://github.com/basictheprogram/ansible-role-traefik/actions/workflows/ci.yml)
[![Ansible Galaxy](https://img.shields.io/badge/ansible--galaxy-traefik-blue.svg?style=popout-square)](https://galaxy.ansible.com/realtime/traefik)
[![Ansible Role](https://img.shields.io/ansible/role/d/realtime/traefik.svg?style=popout-square)](https://galaxy.ansible.com/realtime/traefik)

<!-- TOC depthFrom:2 depthTo:6 withLinks:1 updateOnSave:1 orderedList:0 -->

- [Description](#description)
- [Installation](#installation)
- [Requirements](#requirements)
- [Role Variables](#role-variables)
	- [In-Depth Configuration](#in-depth-configuration)
- [Fork History and Breaking Changes](#fork-history-and-breaking-changes)
	- [Breaking changes from arillso/ansible.traefik](#breaking-changes-from-arillsoansibletraefik)
		- [`traefik_configuration_file`](#traefikconfigurationfile)
		- [`traefik_api`](#traefikapi)
		- [`traefik_ping`](#traefikping)

<!-- /TOC -->

## Description

[Traefik](https://doc.traefik.io/traefik/) is a reverse proxy written in Go.
It can be used in multiple situations with many providers (Kubernetes, Swarm,
...). Version 3 adds TCP and UDP routing, HTTP/3 support, and a redesigned
middleware and provider model.

This role sets up Traefik v3 on a host as a reverse proxy and load balancer.
This allows you to use one server as a host for multiple containerized
applications.

> **Note:** This role is designed for a single-host Docker deployment.
> Depending on your use case, this might not be what you are looking for.
> For highly-available services, consider Kubernetes or Swarm and deploy
> Traefik there instead.

## Installation

```bash
ansible-galaxy install realtime.traefik
```

Or pin directly to this repository in your `requirements.yml`:

```yaml
roles:
  - name: realtime.traefik
    src: https://github.com/basictheprogram/ansible-role-traefik
    version: main
```

## Requirements

- Docker

## Role Variables

Traefik v3 supports YAML configuration. This role uses that to generate the
static configuration directly from Ansible variables.

There are quick-setup variables for common scenarios and lower-level
`_confkey_` variables for full control over every configuration key.

The quick-setup covers:

- A Let's Encrypt certificate resolver
- Standard HTTP/HTTPS entrypoints
- A standard Docker provider

Quick-setup variables are prefixed with `traefik_qs_`.

| Name                              | Default                      | Description                                                      |
| :-------------------------------- | :--------------------------- | :--------------------------------------------------------------- |
| `traefik_dir`                     | `/etc/traefik`               | where to store traefik data                                      |
| `traefik_hostname`                | `"{{ inventory_hostname }}"` | the hostname of this instance                                    |
| `traefik_network`                 | `traefik_proxy`              | the name of the generated network                                |
| `traefik_qs_send_anonymous_usage` | `false`                      | whether to send anonymous usage                                  |
| `traefik_qs_https`                | `false`                      | whether to set up an HTTPS entrypoint                            |
| `traefik_qs_https_redirect`       | `false`                      | whether to redirect HTTP to HTTPS                                |
| `traefik_qs_https_le`             | `false`                      | whether to set up Let's Encrypt via TLS (requires HTTPS)         |
| `traefik_qs_https_le_mail`        | undefined                    | the email to use for Let's Encrypt (**required**)                |
| `traefik_qs_log_level`            | `ERROR`                      | the log level to apply                                           |
| `traefik_container_name`          | `traefik`                    | the container name                                               |
| `traefik_network_name`            | `traefik_proxy`              | the Docker network name                                          |
| `traefik_network_ipam_subnet`     | `172.16.1.0/24`              | subnet                                                           |
| `traefik_network_ipam_gateway`    | `172.16.1.1`                 | gateway                                                          |
| `traefik_network_ipam_iprange`    | `172.16.1.0/24`              | iprange                                                          |
| `traefik_image`                   | `traefik`                    | the Docker image to use                                          |
| `traefik_add_volumes`             | `[]`                         | additional volumes to mount                                      |
| `traefik_ports`                   | `['80:80', '443:443']`       | published ports                                                  |
| `traefik_labels`                  | `{}`                         | labels to set on the Traefik container                           |

The default names for generated configuration objects are:

- Entrypoints: `http`, `https`
- Providers: `docker`
- Certificate resolvers: `letsencrypt`

### In-Depth Configuration

This role also exposes the full Traefik static configuration via `_confkey_`
variables. These are merged into the configuration **after** the quick-setup
values using the Ansible
[`combine()`](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/combine_filter.html)
filter in non-recursive mode, so you can override any quick-setup key by
supplying the same key here.

| Name                                    | Default   | Description                                                                           |
| :-------------------------------------- | :-------- | :------------------------------------------------------------------------------------ |
| `traefik_confkey_global`                | undefined | [see Docs](https://doc.traefik.io/traefik/reference/static-configuration/file/)       |
| `traefik_confkey_serversTransport`      | undefined | [see Docs](https://doc.traefik.io/traefik/reference/static-configuration/cli-ref/)    |
| `traefik_confkey_entryPoints`           | undefined | [see Docs](https://doc.traefik.io/traefik/routing/entrypoints/)                       |
| `traefik_confkey_providers`             | undefined | [see Docs](https://doc.traefik.io/traefik/providers/docker/)                          |
| `traefik_confkey_api`                   | undefined | [see Docs](https://doc.traefik.io/traefik/operations/api/)                            |
| `traefik_confkey_metrics`               | undefined | [see Docs](https://doc.traefik.io/traefik/observability/metrics/overview/)            |
| `traefik_confkey_ping`                  | undefined | [see Docs](https://doc.traefik.io/traefik/operations/ping/)                           |
| `traefik_confkey_log`                   | undefined | [see Docs](https://doc.traefik.io/traefik/observability/logs/)                        |
| `traefik_confkey_accessLog`             | undefined | [see Docs](https://doc.traefik.io/traefik/observability/access-logs/)                 |
| `traefik_confkey_tracing`               | undefined | [see Docs](https://doc.traefik.io/traefik/observability/tracing/overview/)            |
| `traefik_confkey_hostResolver`          | undefined | [see Docs](https://doc.traefik.io/traefik/reference/static-configuration/file/)       |
| `traefik_confkey_certificatesResolvers` | undefined | [see Docs](https://doc.traefik.io/traefik/https/acme/)                                |

## Fork History and Breaking Changes

This role is a fork of [arillso/ansible.traefik](https://github.com/arillso/ansible.traefik),
which was itself a fork of [sbaerlocher/ansible.traefik](https://github.com/sbaerlocher/ansible.traefik).

**This fork does not guarantee compatibility with either upstream role.**

Notable divergences from upstream:

- Targets Traefik **v3** (upstream targets v2). The Traefik v2 → v3 migration
  introduces breaking changes in static and dynamic configuration; see the
  [official migration guide](https://doc.traefik.io/traefik/migration/v2-to-v3/).
- CI has moved from Travis CI to **GitHub Actions**.
- All module names use FQCNs (`ansible.builtin.*`, `community.docker.*`).
- Requires **ansible-core >= 2.12**.
- Handler, task, and variable names may differ from upstream; do not assume
  drop-in compatibility when upgrading from either fork.

### Breaking changes from arillso/ansible.traefik

The following variables from `arillso/ansible.traefik` (and its predecessor
`sbaerlocher/ansible.traefik`) have no equivalent in this role and will be
silently ignored if set.

#### `traefik_configuration_file`

The `traefik_configuration_file` variable has no effect. The Traefik v2
configuration format is not compatible with v3. Use the
[Traefik v3 static configuration docs](https://doc.traefik.io/traefik/reference/static-configuration/file/)
and recreate your configuration using the `traefik_confkey_*` variables.

#### `traefik_api`

The Traefik v3 API supports
[multiple configuration options](https://doc.traefik.io/traefik/operations/api/).
Automatic API config generation was dropped because it cannot be cleanly
merged with a custom configuration. To expose a simple insecure API on
container port `8080` (not recommended for production):

```yaml
traefik_confkey_api:
  insecure: true
  dashboard: true
traefik_ports:
  - '80:80'
  - '443:443'
  - '8080:8080'
```

#### `traefik_ping`

Similarly, the ping endpoint requires explicit entrypoint configuration.
See the [Traefik ping docs](https://doc.traefik.io/traefik/operations/ping/).
Example — exposing ping on port `8082`:

```yaml
traefik_confkey_entryPoints:
  ping:
    address: ':8082'
traefik_confkey_ping:
  entryPoint: 'ping'
traefik_ports:
  - '80:80'
  - '443:443'
  - '8082:8082'
```
