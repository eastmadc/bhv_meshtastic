#!/usr/bin/env python3
"""Production flasher for Biohacking Village Heltec V4 badges."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENVIRONMENT = "heltec-v4"
DEFAULT_CHANNELS = ("BHV", "BHV Info")
DEFAULT_RECORDS_DIR = ROOT / ".local" / "bhv-flasher"
DEFAULT_FIRMWARE_DIR = ROOT / "firmware"
BADGE_ID_COUNT = 200
ESPRESSIF_USB_VIDS = {0x303A, 0x10C4, 0x1A86, 0x0403}
MAC_RE = re.compile(r"\b(?:MAC|BASE MAC):\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.I)
SECRET_DEFINE_RE = re.compile(
    r"(?i)(-DUSERPREFS_(?:CHANNEL_\d+_PSK|USE_ADMIN_KEY_\d+|NETWORK_WIFI_PSK|MQTT_PASSWORD)=).*"
)
RECORDS_LOCK = threading.Lock()


class FlasherError(RuntimeError):
    """An expected production-flashing failure."""


@dataclass(frozen=True)
class FirmwareArtifacts:
    factory: Path
    filesystem: Path
    metadata: Path
    filesystem_offset: str
    mcu: str
    platformio_target: str
    version: str
    factory_sha256: str
    filesystem_sha256: str
    info_fingerprint: str = ""


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    hwid: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    location: str | None

    @property
    def likely_badge(self) -> bool:
        text = f"{self.description} {self.hwid}".lower()
        return self.vid in ESPRESSIF_USB_VIDS or any(
            marker in text for marker in ("esp32", "espressif", "cp210", "ch340", "usbmodem")
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    show_output: bool = True,
) -> str:
    printable = " ".join(command)
    if show_output:
        print(f"$ {printable}", flush=True)
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output.append(line)
        if show_output:
            print(SECRET_DEFINE_RE.sub(r"\1<redacted>", line), end="", flush=True)
    return_code = process.wait()
    combined = "".join(output)
    if return_code:
        if not show_output:
            print(SECRET_DEFINE_RE.sub(r"\1<redacted>", combined), file=sys.stderr)
        raise FlasherError(f"Command failed ({return_code}): {printable}")
    return combined


def platformio_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache" / "uv"))
    env.setdefault("PLATFORMIO_CORE_DIR", str(ROOT / ".platformio"))
    env.setdefault("PLATFORMIO_SETTING_ENABLE_TELEMETRY", "no")
    return env


def platformio_command() -> list[str]:
    local_pio = ROOT / ".venv" / "bin" / "pio"
    if local_pio.exists():
        return [str(local_pio)]
    return ["pio"]


def esptool_command() -> list[str]:
    local_python = ROOT / ".venv" / "bin" / "python"
    python = local_python if local_python.exists() else Path(sys.executable)
    packaged = ROOT / ".platformio" / "packages" / "tool-esptoolpy" / "esptool.py"
    if packaged.exists():
        return [str(python), str(packaged)]
    return [str(python), "-m", "esptool"]


def meshtastic_python() -> Path:
    local_python = ROOT / ".venv" / "bin" / "python"
    if not local_python.exists():
        raise FlasherError("Missing .venv/bin/python; create the pinned production environment first")
    return local_python


def build_firmware(environment: str) -> FirmwareArtifacts:
    run_command(
        [*platformio_command(), "run", "-e", environment],
        env=platformio_environment(),
    )
    return discover_artifacts(environment=environment)


def environment_for_build(admin_build: bool) -> str:
    return "heltec-v4-admin" if admin_build else DEFAULT_ENVIRONMENT


def release_dir(admin_build: bool) -> Path:
    return DEFAULT_FIRMWARE_DIR / ("admin" if admin_build else "attendee")


def configured_info_fingerprint() -> str:
    """Derive and validate the BHV Info fingerprint from the tracked preferences."""
    prefs_path = ROOT / "userPrefs.jsonc"
    without_comments = re.sub(r"//.*$", "", prefs_path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    try:
        prefs = json.loads(without_comments)
    except json.JSONDecodeError as exc:
        raise FlasherError(f"Invalid preferences file: {prefs_path}") from exc

    psk_value = prefs.get("USERPREFS_CHANNEL_1_PSK", "")
    psk = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", psk_value))
    if len(psk) not in (16, 32):
        raise FlasherError("USERPREFS_CHANNEL_1_PSK must contain a 16- or 32-byte key")
    derived = hashlib.sha256(psk).hexdigest()

    configured_value = prefs.get("USERPREFS_BHV_INFO_PSK_SHA256", "")
    configured = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", configured_value))
    if configured and configured.hex() != derived:
        raise FlasherError("Configured BHV Info fingerprint does not match USERPREFS_CHANNEL_1_PSK")
    return derived


def _metadata_file_entry(metadata: dict[str, Any], suffix: str) -> str:
    matches = [
        item["name"]
        for item in metadata.get("files", [])
        if isinstance(item, dict) and str(item.get("name", "")).endswith(suffix)
    ]
    if len(matches) != 1:
        raise FlasherError(f"Metadata must identify exactly one {suffix} artifact")
    return matches[0]


def discover_artifacts(
    *,
    environment: str = DEFAULT_ENVIRONMENT,
    factory: Path | None = None,
) -> FirmwareArtifacts:
    build_dir = ROOT / ".pio" / "build" / environment
    if factory is None:
        metadata_candidates = sorted(
            build_dir.glob("firmware-*.mt.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not metadata_candidates:
            raise FlasherError(f"No firmware metadata found in {build_dir}; run the build first")
        metadata_path = metadata_candidates[0]
    else:
        factory = factory.resolve()
        if not factory.name.endswith(".factory.bin"):
            raise FlasherError("Firmware must be a *.factory.bin image")
        metadata_path = factory.with_name(factory.name.removesuffix(".factory.bin") + ".mt.json")

    if not metadata_path.exists():
        raise FlasherError(f"Missing firmware metadata: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_dir = metadata_path.parent
    factory_path = factory or metadata_dir / _metadata_file_entry(metadata, ".factory.bin")
    filesystem_entries = [
        item
        for item in metadata.get("files", [])
        if isinstance(item, dict) and item.get("part_name") == "spiffs"
    ]
    if len(filesystem_entries) != 1:
        raise FlasherError("Metadata must identify exactly one filesystem artifact")
    filesystem_path = metadata_dir / filesystem_entries[0]["name"]

    partitions = metadata.get("part", [])
    spiffs = [
        part
        for part in partitions
        if isinstance(part, dict) and part.get("subtype") == "spiffs"
    ]
    if len(spiffs) != 1 or not spiffs[0].get("offset"):
        raise FlasherError("Metadata must identify the filesystem partition offset")

    mcu = str(metadata.get("mcu", "")).lower()
    if mcu != "esp32s3":
        raise FlasherError(f"Expected esp32s3 metadata, found {mcu or 'unknown'}")
    for path in (factory_path, filesystem_path):
        if not path.exists():
            raise FlasherError(f"Missing build artifact: {path}")

    version = factory_path.name.removeprefix("firmware-").removesuffix(".factory.bin")
    return FirmwareArtifacts(
        factory=factory_path.resolve(),
        filesystem=filesystem_path.resolve(),
        metadata=metadata_path.resolve(),
        filesystem_offset=str(spiffs[0]["offset"]),
        mcu=mcu,
        platformio_target=str(metadata.get("platformioTarget", environment)),
        version=version,
        factory_sha256=sha256_file(factory_path),
        filesystem_sha256=sha256_file(filesystem_path),
    )


def publish_artifacts(artifacts: FirmwareArtifacts, *, admin_build: bool) -> FirmwareArtifacts:
    """Copy a completed build into the fixed production firmware set."""
    destination = release_dir(admin_build)
    destination.mkdir(parents=True, exist_ok=True)
    for source in (artifacts.factory, artifacts.filesystem, artifacts.metadata):
        shutil.copy2(source, destination / source.name)

    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "build_type": "admin" if admin_build else "attendee",
        "platformio_target": artifacts.platformio_target,
        "info_fingerprint": configured_info_fingerprint(),
        "factory": artifacts.factory.name,
        "filesystem": artifacts.filesystem.name,
        "metadata": artifacts.metadata.name,
        "factory_sha256": artifacts.factory_sha256,
        "filesystem_sha256": artifacts.filesystem_sha256,
    }
    manifest_path = destination / "release.json"
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_path, manifest_path)
    return load_release_artifacts(admin_build)


def load_release_artifacts(admin_build: bool) -> FirmwareArtifacts:
    destination = release_dir(admin_build)
    manifest_path = destination / "release.json"
    build_type = "admin" if admin_build else "attendee"
    if not manifest_path.exists():
        raise FlasherError(
            f"No prepared {build_type} firmware in {destination}; run "
            f"'bin/bhv-flasher.py build{' --admin' if admin_build else ''}' first"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FlasherError(f"Invalid release manifest: {manifest_path}") from exc
    if manifest.get("build_type") != build_type:
        raise FlasherError(f"Wrong build type in {manifest_path}")
    expected_target = environment_for_build(admin_build)
    if manifest.get("platformio_target") != expected_target:
        raise FlasherError(f"Wrong PlatformIO target in {manifest_path}")
    factory_name = manifest.get("factory")
    if not isinstance(factory_name, str) or Path(factory_name).name != factory_name:
        raise FlasherError(f"Invalid factory filename in {manifest_path}")
    artifacts = discover_artifacts(
        environment=environment_for_build(admin_build),
        factory=destination / factory_name,
    )

    if artifacts.platformio_target != expected_target:
        raise FlasherError(
            f"Prepared {build_type} image is for {artifacts.platformio_target}, not {expected_target}"
        )
    for field in ("factory_sha256", "filesystem_sha256"):
        if manifest.get(field) != getattr(artifacts, field):
            raise FlasherError(f"Prepared {build_type} firmware failed its {field} integrity check")
    fingerprint = str(manifest.get("info_fingerprint", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise FlasherError(f"Invalid BHV Info fingerprint in {manifest_path}")
    return replace(artifacts, info_fingerprint=fingerprint)


def resolve_artifacts(args: argparse.Namespace) -> FirmwareArtifacts:
    return load_release_artifacts(args.admin_build)


def list_serial_ports() -> list[PortInfo]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise FlasherError("pyserial is required; run this tool with .venv/bin/python") from exc
    return [
        PortInfo(
            device=port.device,
            description=port.description or "",
            hwid=port.hwid or "",
            vid=port.vid,
            pid=port.pid,
            serial_number=port.serial_number,
            location=port.location,
        )
        for port in list_ports.comports()
    ]


def select_port(requested: str | None) -> PortInfo:
    ports = list_serial_ports()
    if requested:
        for port in ports:
            if port.device == requested:
                return port
        raise FlasherError(f"Requested serial port is not present: {requested}")
    candidates = [port for port in ports if port.likely_badge]
    if len(candidates) != 1:
        names = ", ".join(port.device for port in candidates) or "none"
        raise FlasherError(
            f"Expected exactly one likely badge serial port, found {len(candidates)} ({names}); use --port"
        )
    return candidates[0]


def probe_chip(port: str, *, dry_run: bool = False) -> tuple[str, str]:
    command = [*esptool_command(), "--chip", "esp32s3", "--port", port, "chip_id"]
    if dry_run:
        print("$ " + " ".join(command))
        return "DRY-RUN", "ESP32-S3"
    output = run_command(command)
    if "ESP32-S3" not in output.upper():
        raise FlasherError("Connected device did not identify as an ESP32-S3")
    mac_match = MAC_RE.search(output)
    if not mac_match:
        raise FlasherError("Could not read the ESP32-S3 MAC address")
    return mac_match.group(1).lower(), "ESP32-S3"


def flash_artifacts(
    port: str,
    artifacts: FirmwareArtifacts,
    *,
    baud: int,
    dry_run: bool = False,
    progress: Any = None,
) -> int:
    erase = [
        *esptool_command(),
        "--chip",
        artifacts.mcu,
        "--port",
        port,
        "erase_flash",
    ]
    write = [
        *esptool_command(),
        "--chip",
        artifacts.mcu,
        "--port",
        port,
        "--baud",
        str(baud),
        "--before",
        "default_reset",
        "--after",
        "hard_reset",
        "write_flash",
        "0x0",
        str(artifacts.factory),
        artifacts.filesystem_offset,
        str(artifacts.filesystem),
    ]
    if dry_run:
        print("$ " + " ".join(erase))
        print("$ " + " ".join(write))
        return 0
    if progress:
        progress("erase", "Erasing flash")
    run_command(erase)
    if progress:
        progress("write", "Writing and verifying firmware")
    output = run_command(write)
    verification_markers = output.count("Hash of data verified")
    if verification_markers < 2:
        raise FlasherError(
            f"esptool completed but reported only {verification_markers} verified image(s)"
        )
    return verification_markers


def badge_names(asset: str, *, admin_build: bool = False) -> tuple[str, str]:
    clean = asset.strip()
    if not clean:
        raise FlasherError("Asset ID cannot be empty")
    match = re.search(r"(\d+)$", clean)
    suffix = match.group(1).zfill(3) if match else clean
    name_prefix = "BHV Admin" if admin_build else "BHV Badge"
    short_prefix = "A" if admin_build else "B"
    short = (
        f"{short_prefix}{suffix[-3:]}"
        if suffix[-3:].isdigit()
        else re.sub(r"\W", "", clean).upper()[-4:]
    )
    if not short:
        raise FlasherError(f"Cannot derive a short name from asset ID {asset!r}")
    return f"{name_prefix} {suffix}", short[:4]


def _urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def channel_summary(channel_url: str) -> list[dict[str, str]]:
    try:
        from meshtastic.protobuf import apponly_pb2
    except ImportError as exc:
        raise FlasherError("The pinned Meshtastic Python client is unavailable") from exc
    fragment = channel_url.rsplit("#", 1)[-1]
    channel_set = apponly_pb2.ChannelSet()
    try:
        channel_set.ParseFromString(_urlsafe_decode(fragment))
    except Exception as exc:
        raise FlasherError("Could not decode the badge channel configuration") from exc
    return [
        {
            "name": setting.name,
            "psk_sha256": hashlib.sha256(bytes(setting.psk)).hexdigest(),
        }
        for setting in channel_set.settings
    ]


def provision_and_verify(
    port: str,
    *,
    long_name: str,
    short_name: str,
    expected_channels: Sequence[str],
    expected_info_fingerprint: str | None,
    timeout: int,
) -> dict[str, Any]:
    # Importing through the pinned interpreter keeps production client behavior reproducible.
    helper = ROOT / "bin" / "bhv-provision.py"
    command = [
        str(meshtastic_python()),
        str(helper),
        "--port",
        port,
        "--long-name",
        long_name,
        "--short-name",
        short_name,
        "--timeout",
        str(timeout),
    ]
    output = run_command(command, show_output=False)
    json_lines = [line for line in output.splitlines() if line.startswith("{")]
    try:
        result = json.loads(json_lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise FlasherError("Provisioning helper returned invalid data") from exc

    if result.get("long_name") != long_name or result.get("short_name") != short_name:
        raise FlasherError("Owner-name readback did not match the requested badge identity")
    channels = channel_summary(result.pop("channel_url"))
    actual_names = [channel["name"] for channel in channels]
    if actual_names != list(expected_channels):
        raise FlasherError(
            f"Channel readback mismatch: expected {list(expected_channels)!r}, found {actual_names!r}"
        )
    if expected_info_fingerprint:
        expected = expected_info_fingerprint.lower()
        actual = channels[1]["psk_sha256"] if len(channels) > 1 else ""
        if actual != expected:
            raise FlasherError("BHV Info PSK fingerprint did not match the released profile")
    result["channels"] = channels
    return result


def read_events(records_dir: Path) -> list[dict[str, Any]]:
    path = records_dir / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise FlasherError(f"Invalid audit record at {path}:{line_number}") from exc
    return events


def active_pass_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve the current assignments while retaining append-only history."""
    active: dict[str, dict[str, Any]] = {}
    for event in events:
        asset = event.get("asset")
        if not asset:
            continue
        if event.get("status") == "PASS":
            active[str(asset)] = event
        elif event.get("status") == "REMOVED":
            active.pop(str(asset), None)
    return list(active.values())


def enforce_duplicate_policy(
    events: Iterable[dict[str, Any]],
    *,
    asset: str,
    mac: str,
    allow_reflash: bool,
) -> int:
    relevant = [event for event in events if event.get("asset") == asset]
    passed = active_pass_events(events)
    if not allow_reflash and any(event.get("asset") == asset for event in passed):
        raise FlasherError(f"Asset {asset} already has a PASS record; use --allow-reflash for rework")
    for event in passed:
        if event.get("asset") == asset and event.get("mac") not in (None, mac):
            raise FlasherError(f"Asset {asset} is already assigned to a different MAC")
        if event.get("mac") == mac and event.get("asset") != asset:
            raise FlasherError(f"MAC {mac} is already assigned to asset {event.get('asset')}")
    return len(relevant) + 1


def next_available_asset(events: Iterable[dict[str, Any]], *, admin_build: bool) -> str:
    """Return the first production ID without a successful flash record."""
    prefix = "ADMIN-" if admin_build else ""
    used = {str(event.get("asset")) for event in active_pass_events(events)}
    for number in range(1, BADGE_ID_COUNT + 1):
        asset = f"{prefix}{number:03d}"
        if asset not in used:
            return asset
    raise FlasherError(f"All {BADGE_ID_COUNT} {('admin' if admin_build else 'attendee')} badge IDs have PASS records")


def next_available_assets(
    events: Iterable[dict[str, Any]],
    *,
    admin_build: bool,
    count: int,
    reserved: Iterable[str] = (),
) -> list[str]:
    """Reserve the first available production IDs for a parallel batch."""
    if count < 0:
        raise ValueError("count must not be negative")
    prefix = "ADMIN-" if admin_build else ""
    used = {str(event.get("asset")) for event in active_pass_events(events)}
    used.update(reserved)
    available = [
        f"{prefix}{number:03d}"
        for number in range(1, BADGE_ID_COUNT + 1)
        if f"{prefix}{number:03d}" not in used
    ]
    if len(available) < count:
        raise FlasherError(
            f"Only {len(available)} {('admin' if admin_build else 'attendee')} badge IDs remain"
        )
    return available[:count]


CSV_FIELDS = (
    "timestamp",
    "date_flashed",
    "asset",
    "attempt",
    "status",
    "reason",
    "station",
    "operator",
    "port",
    "mac",
    "node_id",
    "long_name",
    "short_name",
    "badge_name",
    "build_type",
    "admin_build",
    "firmware_version",
    "factory_sha256",
    "filesystem_sha256",
    "duration_seconds",
)


def update_inventory(records_dir: Path, event: dict[str, Any]) -> None:
    """Update the latest-known successful flash state, keyed by immutable hardware MAC."""
    if event.get("status") not in ("PASS", "REMOVED") or not event.get("mac"):
        return

    inventory_path = records_dir / "inventory.json"
    if inventory_path.exists():
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FlasherError(f"Invalid inventory file: {inventory_path}") from exc
    else:
        inventory = {"schema_version": 1, "badges": {}}

    if event["status"] == "REMOVED":
        inventory.setdefault("badges", {}).pop(event["mac"], None)
    else:
        inventory.setdefault("badges", {})[event["mac"]] = {
            field: event.get(field)
            for field in CSV_FIELDS
            if field not in ("status", "reason", "duration_seconds")
        }
    inventory["updated_at"] = event["date_flashed"]

    temporary_path = inventory_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_path, inventory_path)

    inventory_csv = records_dir / "inventory.csv"
    rows = sorted(
        inventory["badges"].values(),
        key=lambda row: (str(row.get("asset", "")), str(row.get("mac", ""))),
    )
    with inventory_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_event(records_dir: Path, event: dict[str, Any]) -> None:
    with RECORDS_LOCK:
        records_dir.mkdir(parents=True, exist_ok=True)
        with (records_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        manifest_path = records_dir / "manifest.csv"
        write_header = not manifest_path.exists()
        with manifest_path.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(event)
        update_inventory(records_dir, event)


def report_progress(args: argparse.Namespace, phase: str, detail: str) -> None:
    callback = getattr(args, "progress_callback", None)
    if callback:
        callback(phase, detail)


def flash_one(args: argparse.Namespace, asset: str) -> bool:
    started = time.monotonic()
    timestamp = utc_now()
    args.last_error = ""
    report_progress(args, "prepare", "Validating released firmware")
    artifacts = resolve_artifacts(args)
    report_progress(args, "connect", f"Opening {args.port or 'detected badge port'}")
    if args.dry_run:
        port = PortInfo(
            device=args.port or "/dev/DRY_RUN",
            description="dry run",
            hwid="",
            vid=None,
            pid=None,
            serial_number=None,
            location=None,
        )
    else:
        port = select_port(args.port)
    mac = ""
    attempt = 1
    event: dict[str, Any] = {
        "timestamp": timestamp,
        "date_flashed": timestamp,
        "asset": asset,
        "status": "FAIL",
        "reason": "",
        "station": args.station,
        "operator": args.operator,
        "port": port.device,
        "port_description": port.description,
        "port_serial": port.serial_number,
        "firmware_version": artifacts.version,
        "factory_sha256": artifacts.factory_sha256,
        "filesystem_sha256": artifacts.filesystem_sha256,
        "filesystem_offset": artifacts.filesystem_offset,
        "build_type": args.build_type,
        "admin_build": args.admin_build,
    }
    try:
        report_progress(args, "probe", "Reading ESP32-S3 identity")
        mac, chip = probe_chip(port.device, dry_run=args.dry_run)
        event.update({"mac": mac, "chip": chip})
        attempt = enforce_duplicate_policy(
            read_events(args.records_dir),
            asset=asset,
            mac=mac,
            allow_reflash=args.allow_reflash,
        )
        event["attempt"] = attempt
        long_name, short_name = badge_names(asset, admin_build=args.admin_build)
        event.update({"long_name": long_name, "short_name": short_name, "badge_name": long_name})
        markers = flash_artifacts(
            port.device,
            artifacts,
            baud=args.baud,
            dry_run=args.dry_run,
            progress=lambda phase, detail: report_progress(args, phase, detail),
        )
        event["flash_verification_markers"] = markers
        if not args.skip_provision and not args.dry_run:
            report_progress(args, "boot", f"Waiting {args.boot_wait}s for first boot")
            print(f"Waiting {args.boot_wait}s for first boot...", flush=True)
            time.sleep(args.boot_wait)
            report_progress(args, "provision", f"Naming and verifying {long_name}")
            provisioned = provision_and_verify(
                port.device,
                long_name=long_name,
                short_name=short_name,
                expected_channels=args.expected_channel,
                expected_info_fingerprint=artifacts.info_fingerprint,
                timeout=args.api_timeout,
            )
            event.update(provisioned)
        event["status"] = "DRY_RUN" if args.dry_run else "PASS"
        event["reason"] = ""
        report_progress(args, "pass", f"{asset} passed")
        print(f"{event['status']}: {asset} ({mac})", flush=True)
        return True
    except Exception as exc:
        event["attempt"] = attempt
        event["reason"] = str(exc)
        args.last_error = str(exc)
        report_progress(args, "fail", str(exc))
        print(f"FAIL: {asset}: {exc}", file=sys.stderr, flush=True)
        return False
    finally:
        event["duration_seconds"] = round(time.monotonic() - started, 1)
        if not args.dry_run:
            append_event(args.records_dir, event)


def add_flash_arguments(parser: argparse.ArgumentParser, *, asset_required: bool) -> None:
    if asset_required:
        parser.add_argument("--asset", required=True, help="Badge asset ID, for example 001")
    parser.add_argument("--port", help="Exact serial port; auto-detects only when exactly one badge is present")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--boot-wait", type=int, default=12)
    parser.add_argument("--api-timeout", type=int, default=45)
    parser.add_argument("--skip-provision", action="store_true", help="Flash only; do not name or verify config")
    parser.add_argument(
        "--expected-channel",
        action="append",
        default=None,
        help="Expected enabled channel name in index order; repeat for each channel",
    )
    parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    parser.add_argument("--station", default=socket.gethostname())
    parser.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    parser.add_argument(
        "--admin",
        "--admin-build",
        dest="admin_build",
        action="store_true",
        help="Flash the admin publisher image; without this flag, flash the attendee image",
    )
    parser.add_argument("--allow-reflash", action="store_true")
    parser.add_argument("--dry-run", action="store_true")


def normalize_args(args: argparse.Namespace) -> None:
    args.build_type = "admin" if args.admin_build else "attendee"
    args.records_dir = args.records_dir.resolve()
    if args.expected_channel is None:
        args.expected_channel = list(DEFAULT_CHANNELS)
    if len(args.expected_channel) != 2 and not args.skip_provision:
        raise FlasherError("Production verification expects exactly two enabled channels")


def command_list(_: argparse.Namespace) -> int:
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found.")
        return 0
    for port in ports:
        marker = "*" if port.likely_badge else " "
        vid_pid = f"{port.vid:04x}:{port.pid:04x}" if port.vid is not None and port.pid is not None else "unknown"
        print(f"{marker} {port.device:30} {vid_pid}  {port.description}")
    print("* likely badge port")
    return 0


def command_build(args: argparse.Namespace) -> int:
    environment = environment_for_build(args.admin)
    artifacts = publish_artifacts(build_firmware(environment), admin_build=args.admin)
    print(json.dumps({key: str(value) for key, value in asdict(artifacts).items()}, indent=2))
    return 0


def command_flash(args: argparse.Namespace) -> int:
    normalize_args(args)
    return 0 if flash_one(args, args.asset) else 1


def command_remove(args: argparse.Namespace) -> int:
    args.records_dir = args.records_dir.resolve()
    events = read_events(args.records_dir)
    matches = [
        event
        for event in active_pass_events(events)
        if str(event.get("asset", "")).casefold() == args.asset.casefold()
    ]
    if len(matches) != 1:
        raise FlasherError(f"No active PASS assignment found for {args.asset}")
    assigned = matches[0]
    timestamp = utc_now()
    event = {
        **{field: assigned.get(field) for field in CSV_FIELDS},
        "timestamp": timestamp,
        "date_flashed": timestamp,
        "asset": assigned["asset"],
        "attempt": sum(1 for item in events if item.get("asset") == assigned["asset"]) + 1,
        "status": "REMOVED",
        "reason": args.reason,
        "station": args.station,
        "operator": args.operator,
        "duration_seconds": 0,
    }
    append_event(args.records_dir, event)
    print(f"REMOVED: {assigned['asset']} ({assigned['mac']})")
    return 0


def command_station(args: argparse.Namespace) -> int:
    normalize_args(args)
    print("BHV flashing station ready. Badge IDs are assigned from the first available production ID.")
    failures = 0
    while True:
        asset = next_available_asset(read_events(args.records_dir), admin_build=args.admin_build)
        long_name, short_name = badge_names(asset, admin_build=args.admin_build)
        try:
            response = input(
                f"Next: {asset} ({long_name} / {short_name}). "
                "Connect the badge and press Enter to flash, or q to quit: "
            ).strip()
        except EOFError:
            break
        if response.lower() in ("q", "quit", "exit"):
            break
        if not flash_one(args, asset):
            failures += 1
            print(f"Badge {asset} did not pass and remains the next available ID.\n")
        else:
            print("Disconnect this badge and connect the next one.\n")
    return 1 if failures else 0


def command_gui(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(ROOT / "bin" / "bhv-flasher-gui.py"),
        "--records-dir",
        str(args.records_dir.resolve()),
    ]
    if args.admin:
        command.append("--admin")
    return subprocess.call(command, cwd=ROOT)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List serial ports")
    list_parser.set_defaults(func=command_list)

    build_parser = subparsers.add_parser("build", help="Build the released firmware once")
    build_parser.add_argument("--admin", action="store_true", help="Build the admin publisher image")
    build_parser.set_defaults(func=command_build)

    flash_parser = subparsers.add_parser("flash", help="Flash and verify one badge")
    add_flash_arguments(flash_parser, asset_required=True)
    flash_parser.set_defaults(func=command_flash)

    remove_parser = subparsers.add_parser("remove", help="Release a badge assignment while retaining its audit history")
    remove_parser.add_argument("--asset", required=True, help="Assigned badge ID to release")
    remove_parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    remove_parser.add_argument("--station", default=socket.gethostname())
    remove_parser.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    remove_parser.add_argument("--reason", default="Assignment removed by operator")
    remove_parser.set_defaults(func=command_remove)

    station_parser = subparsers.add_parser("station", help="Run a scan/flash/verify production loop")
    add_flash_arguments(station_parser, asset_required=False)
    station_parser.set_defaults(func=command_station)

    gui_parser = subparsers.add_parser("gui", help="Open the three-port parallel flashing station")
    gui_parser.add_argument("--admin", action="store_true", help="Start in admin-publisher mode")
    gui_parser.add_argument("--records-dir", type=Path, default=DEFAULT_RECORDS_DIR)
    gui_parser.set_defaults(func=command_gui)
    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (FlasherError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
