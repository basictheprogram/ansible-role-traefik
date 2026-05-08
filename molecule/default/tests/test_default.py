"""Molecule testinfra tests for ansible-role-traefik.

These tests verify the converged state of the role against the variables
defined in molecule/default/playbook.yml. They are integration tests —
they inspect real filesystem state, Docker objects, and rendered file
content on the test instance.

Run during molecule verify:
    molecule verify
Or as part of the full test sequence:
    molecule test
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from testinfra.host import Host

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_yaml(host: Host, path: str) -> Any:
    """Read a file from the host and parse it as YAML.

    Returns the parsed object, or raises AssertionError if the file is not valid YAML.
    """
    content = host.file(path).content_string
    return yaml.safe_load(content)


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/traefik",
        "/etc/traefik/dynamic",
        "/var/lib/traefik/certs",
        "/opt/traefik",
    ],
)
def test_directories_exist(host: Host, path: str) -> None:
    d = host.file(path)
    assert d.exists, f"{path} does not exist"
    assert d.is_directory, f"{path} is not a directory"


@pytest.mark.parametrize(
    "path",
    [
        "/etc/traefik",
        "/etc/traefik/dynamic",
        "/var/lib/traefik/certs",
        "/opt/traefik",
    ],
)
def test_directories_owned_by_root(host: Host, path: str) -> None:
    d = host.file(path)
    assert d.user == "root"
    assert d.group == "root"


@pytest.mark.parametrize(
    "path",
    [
        "/etc/traefik",
        "/etc/traefik/dynamic",
        "/var/lib/traefik/certs",
        "/opt/traefik",
    ],
)
def test_directories_permissions(host: Host, path: str) -> None:
    assert host.file(path).mode == 0o755


# ---------------------------------------------------------------------------
# File presence and permissions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected_mode"),
    [
        ("/etc/traefik/traefik.yml", 0o644),
        ("/etc/traefik/dynamic/middlewares.yml", 0o644),
        ("/etc/traefik/dynamic/sites.yml", 0o644),
        ("/etc/traefik/dynamic/tls.yml", 0o644),
        ("/opt/traefik/compose.yml", 0o644),
    ],
)
def test_config_files_exist_with_correct_permissions(host: Host, path: str, expected_mode: int) -> None:
    f = host.file(path)
    assert f.exists, f"{path} does not exist"
    assert f.is_file, f"{path} is not a regular file"
    assert f.mode == expected_mode, f"{path} mode is {oct(f.mode)}, expected {oct(expected_mode)}"
    assert f.user == "root"
    assert f.group == "root"


def test_secrets_file_exists(host: Host) -> None:
    f = host.file("/opt/traefik/.env.secrets")
    assert f.exists


def test_secrets_file_permissions(host: Host) -> None:
    """Credentials file must be readable by root only."""
    f = host.file("/opt/traefik/.env.secrets")
    assert f.mode == 0o600
    assert f.user == "root"
    assert f.group == "root"


def test_secrets_file_no_unrendered_jinja(host: Host) -> None:
    """Ensure no Jinja2 template expressions leaked into the rendered file."""
    content = host.file("/opt/traefik/.env.secrets").content_string
    assert "{{" not in content
    assert "}}" not in content


def test_secrets_file_contains_aws_key(host: Host) -> None:
    """Fake test credentials from playbook.yml should be present."""
    content = host.file("/opt/traefik/.env.secrets").content_string
    assert "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE" in content
    assert "AWS_SECRET_ACCESS_KEY=" in content
    assert "AWS_REGION=us-east-1" in content


def test_no_legacy_single_acme_json(host: Host) -> None:
    """The old single-file HTTP-01 cert store must not exist."""
    assert not host.file("/var/lib/traefik/certs/acme.json").exists


# ---------------------------------------------------------------------------
# YAML validity — all rendered configs must parse cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/traefik/traefik.yml",
        "/etc/traefik/dynamic/middlewares.yml",
        "/etc/traefik/dynamic/sites.yml",
        "/etc/traefik/dynamic/tls.yml",
        "/opt/traefik/compose.yml",
    ],
)
def test_config_files_are_valid_yaml(host: Host, path: str) -> None:
    result = host.run(f"python3 -c \"import yaml, sys; yaml.safe_load(open('{path}'))\" 2>&1")
    assert result.rc == 0, f"{path} is not valid YAML:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Static config — traefik.yml content
# ---------------------------------------------------------------------------


def test_static_config_has_ping(host: Host) -> None:
    """ping: must be present so the healthcheck works."""
    cfg = load_yaml(host, "/etc/traefik/traefik.yml")
    assert "ping" in cfg


def test_static_config_no_http_challenge(host: Host) -> None:
    """DNS-01 only — no httpChallenge block should appear anywhere."""
    content = host.file("/etc/traefik/traefik.yml").content_string
    assert "httpChallenge" not in content


def test_static_config_entrypoint_redirect(host: Host) -> None:
    """Web entrypoint must redirect to websecure."""
    cfg = load_yaml(host, "/etc/traefik/traefik.yml")
    redirect: dict[str, str] = cfg["entryPoints"]["web"].get("http", {}).get("redirections", {}).get("entryPoint", {})
    assert redirect.get("to") == "websecure"
    assert redirect.get("scheme") == "https"


def test_static_config_file_provider(host: Host) -> None:
    """File provider must point at the dynamic config directory."""
    cfg = load_yaml(host, "/etc/traefik/traefik.yml")
    assert cfg["providers"]["file"]["directory"] == "/etc/traefik/dynamic"
    assert cfg["providers"]["file"]["watch"] is True


def test_static_config_docker_provider(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/traefik.yml")
    docker: dict[str, Any] = cfg["providers"]["docker"]
    assert docker["exposedByDefault"] is False
    assert docker["network"] == "traefik_proxy"


# ---------------------------------------------------------------------------
# Dynamic config — middlewares.yml content
# ---------------------------------------------------------------------------


def test_middlewares_has_security_headers(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/middlewares.yml")
    middlewares: dict[str, Any] = cfg["http"]["middlewares"]
    assert "security-headers" in middlewares


def test_middlewares_security_headers_hsts(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/middlewares.yml")
    headers: dict[str, Any] = cfg["http"]["middlewares"]["security-headers"]["headers"]
    assert headers["stsSeconds"] >= 63072000  # 2 years minimum
    assert headers["stsIncludeSubdomains"] is True
    assert headers["frameDeny"] is True


def test_middlewares_allowlist_generated_for_app(host: Host) -> None:
    """Site 'app' has an allowlist — its middleware must be rendered."""
    cfg = load_yaml(host, "/etc/traefik/dynamic/middlewares.yml")
    middlewares: dict[str, Any] = cfg["http"]["middlewares"]
    assert "app-allowlist" in middlewares


def test_middlewares_no_allowlist_for_open_app(host: Host) -> None:
    """Site 'open-app' has no allowlist — no middleware should be rendered."""
    cfg = load_yaml(host, "/etc/traefik/dynamic/middlewares.yml")
    middlewares: dict[str, Any] = cfg["http"]["middlewares"]
    assert "open-app-allowlist" not in middlewares


def test_middlewares_allowlist_cidrs_deduped(host: Host) -> None:
    """CIDRs across referenced groups must be deduplicated."""
    cfg = load_yaml(host, "/etc/traefik/dynamic/middlewares.yml")
    source_range: list[str] = cfg["http"]["middlewares"]["app-allowlist"]["ipAllowList"]["sourceRange"]
    assert len(source_range) == len(set(source_range)), "Duplicate CIDRs found in app-allowlist"


# ---------------------------------------------------------------------------
# Dynamic config — sites.yml content
# ---------------------------------------------------------------------------


def test_sites_has_app_router(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/sites.yml")
    routers: dict[str, Any] = cfg["http"]["routers"]
    assert "app" in routers


def test_sites_app_router_uses_websecure(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/sites.yml")
    assert "websecure" in cfg["http"]["routers"]["app"]["entryPoints"]


def test_sites_app_router_applies_security_headers(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/sites.yml")
    middlewares: list[str] = cfg["http"]["routers"]["app"]["middlewares"]
    assert any("security-headers" in m for m in middlewares)


def test_sites_has_default_servers_transport(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/sites.yml")
    transports: dict[str, Any] = cfg["http"]["serversTransports"]
    assert "default" in transports


# ---------------------------------------------------------------------------
# Dynamic config — tls.yml content
# ---------------------------------------------------------------------------


def test_tls_has_default_store(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/tls.yml")
    assert "stores" in cfg["tls"]
    assert "default" in cfg["tls"]["stores"]


def test_tls_options_minimum_version(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/tls.yml")
    assert cfg["tls"]["options"]["default"]["minVersion"] == "VersionTLS12"


def test_tls_options_sni_strict(host: Host) -> None:
    cfg = load_yaml(host, "/etc/traefik/dynamic/tls.yml")
    assert cfg["tls"]["options"]["default"]["sniStrict"] is True


# ---------------------------------------------------------------------------
# Docker — network and container
# ---------------------------------------------------------------------------


def test_traefik_proxy_network_exists(host: Host) -> None:
    result = host.run("docker network inspect traefik_proxy")
    assert result.rc == 0, "traefik_proxy Docker network does not exist"


def test_traefik_container_running(host: Host) -> None:
    c = host.docker("traefik")
    assert c.is_running


def test_traefik_container_healthy(host: Host) -> None:
    """Container healthcheck must reach healthy before verify runs.

    The role's verify.yml task already polls for this, so by the time
    testinfra runs the container should be healthy.
    """
    result = host.run("docker inspect --format='{{.State.Health.Status}}' traefik")
    assert result.stdout.strip() == "healthy"
