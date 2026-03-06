#!/usr/bin/env python3
"""Update a Cloudflare DNS A record to the current public IPv4 address."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


CF_API_BASE = "https://api.cloudflare.com/client/v4"
IP_PROVIDERS = (
    "https://api.ipify.org?format=json",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


class ApiError(RuntimeError):
    """Raised when Cloudflare API requests fail."""


@dataclass
class Config:
    api_token: str
    zone_id: str
    record_name: str
    ttl: int | None
    proxied: bool | None
    create_missing: bool
    forced_ip: str | None


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Update a Cloudflare DNS A record to your current public IPv4."
    )
    parser.add_argument("--api-token", default=os.getenv("CF_API_TOKEN"))
    parser.add_argument("--zone-id", default=os.getenv("CF_ZONE_ID"))
    parser.add_argument("--record-name", default=os.getenv("CF_RECORD_NAME"))
    parser.add_argument(
        "--ttl",
        type=int,
        default=int(os.getenv("CF_TTL")) if os.getenv("CF_TTL") else None,
        help="DNS TTL in seconds. Use 1 for automatic. Defaults to existing value.",
    )
    parser.add_argument(
        "--create-missing",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("CF_CREATE_MISSING", "true").lower() != "false",
        help="Create record if it does not exist (default: true).",
    )
    parser.add_argument(
        "--ip",
        dest="forced_ip",
        default=None,
        help="Force a specific IPv4 (useful for testing).",
    )
    proxied_group = parser.add_mutually_exclusive_group()
    proxied_group.add_argument(
        "--proxied",
        action="store_true",
        default=os.getenv("CF_PROXIED", "").lower() == "true",
        help="Set record to proxied through Cloudflare.",
    )
    proxied_group.add_argument(
        "--dns-only",
        action="store_true",
        help="Set record as DNS only (not proxied).",
    )
    args = parser.parse_args()

    missing = []
    if not args.api_token:
        missing.append("CF_API_TOKEN / --api-token")
    if not args.zone_id:
        missing.append("CF_ZONE_ID / --zone-id")
    if not args.record_name:
        missing.append("CF_RECORD_NAME / --record-name")
    if missing:
        raise ConfigError(f"Missing required configuration: {', '.join(missing)}")

    if args.ttl is not None and args.ttl < 1:
        raise ConfigError("--ttl must be >= 1")

    proxied_value: bool | None
    if args.dns_only:
        proxied_value = False
    elif "--proxied" in sys.argv or os.getenv("CF_PROXIED"):
        proxied_value = bool(args.proxied)
    else:
        proxied_value = None

    return Config(
        api_token=args.api_token,
        zone_id=args.zone_id,
        record_name=args.record_name,
        ttl=args.ttl,
        proxied=proxied_value,
        create_missing=args.create_missing,
        forced_ip=args.forced_ip,
    )


def get_public_ipv4(forced_ip: str | None = None) -> str:
    if forced_ip:
        ip_obj = ipaddress.ip_address(forced_ip.strip())
        if ip_obj.version != 4:
            raise ConfigError("--ip must be an IPv4 address")
        return str(ip_obj)

    last_error: Exception | None = None
    for url in IP_PROVIDERS:
        try:
            req = request.Request(url, headers={"User-Agent": "auto-dns-updater"})
            with request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode().strip()
            candidate = json.loads(body)["ip"] if "json" in url else body
            ip_obj = ipaddress.ip_address(candidate.strip())
            if ip_obj.version == 4:
                return str(ip_obj)
        except (
            error.URLError,
            error.HTTPError,
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Unable to resolve public IPv4 from providers: {last_error}")


def cf_request(
    method: str, path: str, token: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(
        f"{CF_API_BASE}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            parsed = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        raise ApiError(f"Cloudflare HTTP {exc.code}: {error_body}") from exc
    except (error.URLError, OSError) as exc:
        raise ApiError(f"Cloudflare request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ApiError(f"Cloudflare returned non-JSON response: {exc}") from exc

    if not parsed.get("success"):
        raise ApiError(f"Cloudflare API error: {parsed.get('errors')}")
    return parsed


def find_a_record(config: Config) -> dict[str, Any] | None:
    query = parse.urlencode({"type": "A", "name": config.record_name, "per_page": 1})
    result = cf_request(
        "GET", f"/zones/{config.zone_id}/dns_records?{query}", config.api_token
    )
    records = result.get("result", [])
    return records[0] if records else None


def sync_record(config: Config, current_ip: str) -> str:
    existing = find_a_record(config)
    if existing:
        if existing.get("content") == current_ip:
            return f"No change needed: {config.record_name} already points to {current_ip}"

        ttl_value = config.ttl if config.ttl is not None else int(existing.get("ttl", 1))
        proxied_value = (
            config.proxied
            if config.proxied is not None
            else bool(existing.get("proxied", False))
        )
        payload = {
            "type": "A",
            "name": config.record_name,
            "content": current_ip,
            "ttl": ttl_value,
            "proxied": proxied_value,
        }
        cf_request(
            "PUT",
            f"/zones/{config.zone_id}/dns_records/{existing['id']}",
            config.api_token,
            payload,
        )
        old_ip = existing.get("content")
        return f"Updated {config.record_name}: {old_ip} -> {current_ip}"

    if not config.create_missing:
        raise ApiError(
            f"Record {config.record_name} not found and --no-create-missing is set"
        )

    payload = {
        "type": "A",
        "name": config.record_name,
        "content": current_ip,
        "ttl": config.ttl if config.ttl is not None else 1,
        "proxied": config.proxied if config.proxied is not None else False,
    }
    cf_request("POST", f"/zones/{config.zone_id}/dns_records", config.api_token, payload)
    return f"Created {config.record_name} -> {current_ip}"


def main() -> int:
    try:
        config = parse_args()
        current_ip = get_public_ipv4(config.forced_ip)
        print(f"Detected public IPv4: {current_ip}")
        message = sync_record(config, current_ip)
        print(message)
        return 0
    except (ConfigError, ApiError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
