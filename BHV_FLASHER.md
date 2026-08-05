# BHV Badge Automated Flasher

`bin/bhv-flasher.py` builds, flashes, provisions, verifies, and records production results for the Heltec V4 BHV badges. It
supports a single-port terminal workflow and a three-port parallel macOS GUI.

## Production setup

Use the project virtual environment and the repository-local PlatformIO cache. Before flashing the lot:

1. Freeze and build the attendee firmware defaults, including the production `BHV` and `BHV Info` keys.
2. Run the 10-board release pilot.
3. Archive the released factory image, filesystem image, metadata, and their SHA-256 hashes.
4. Copy the same released artifacts and pinned project environment to every station.

Prepare the attendee and admin release images once. Each command compiles the selected target and copies its factory image,
filesystem image, metadata, hashes, and BHV Info fingerprint into `firmware/attendee/` or `firmware/admin/`:

```sh
.venv/bin/python bin/bhv-flasher.py build
.venv/bin/python bin/bhv-flasher.py build --admin
```

List ports:

```sh
.venv/bin/python bin/bhv-flasher.py list
```

Dry-run one badge without requiring hardware or writing an audit record:

```sh
.venv/bin/python bin/bhv-flasher.py flash \
  --asset 001 \
  --port /dev/cu.usbmodem2101 \
  --dry-run
```

Flash one badge:

```sh
.venv/bin/python bin/bhv-flasher.py flash \
  --asset 001 \
  --port /dev/cu.usbmodem2101
```

Flash an admin publisher badge:

```sh
.venv/bin/python bin/bhv-flasher.py flash \
  --asset ADMIN-001 \
  --port /dev/cu.usbmodem2101 \
  --admin
```

Run an operator station loop:

```sh
.venv/bin/python bin/bhv-flasher.py station
```

Run the three-port macOS GUI:

```sh
.venv/bin/python bin/bhv-flasher.py gui
```

The Tkinter station displays three full-width slots vertically and rescans for devices every second whenever a slot is open. It automatically maps
connected badge devices to unique macOS `/dev/cu.*` paths and shows their USB serial identity or location. A completed slot
remains locked until that badge disappears or a different device identity appears on the same path. `Auto-flash new badges` is
enabled by default, so a newly detected board starts immediately; clear that checkbox to require `Flash This Slot` or
`Flash All Connected`. The flasher reads the ESP32-S3 MAC and checks the active records before erase, so a badge already assigned
in this records directory is rejected without being overwritten. Each slot independently shows its badge ID,
erase/write/boot/provision phase, elapsed time, and PASS or FAIL result. Audit and inventory writes are serialized so
simultaneous completions do not corrupt the production records.

Use the `Admin firmware` checkbox or start directly in admin mode:

```sh
.venv/bin/python bin/bhv-flasher.py gui --admin
```

After a batch completes, disconnect the finished badges and connect the next group. Open slots detect and select the new devices
automatically; `Refresh Ports` remains available for an immediate manual scan.

The station loop reads the audit history, starts with the first attendee ID from `001` through `200` that does not have a PASS,
and advances automatically after each successful badge. Connect the displayed badge and press Enter; enter `q` to stop. A
failed ID remains next so it is not silently skipped. Add `--admin` to use the separate `ADMIN-001` through `ADMIN-200` sequence,
the admin-publisher image, and the `BHV Admin 001` / `A001` naming scheme. If exactly one likely badge port is attached, `--port`
is optional. Use an explicit port when a station exposes any other USB serial devices.

The flasher reads only the prepared image set in `firmware/`. It never rebuilds or chooses a newer build during a production
flash. Attendee is the default; `--admin` selects the separately prepared admin image. The release manifest supplies the
expected `BHV Info` fingerprint and SHA-256 hashes, and the flasher refuses missing, modified, or wrong-target artifacts.

## What a PASS means

A PASS record means the tool:

- positively identified an ESP32-S3 and recorded its hardware MAC;
- rejected duplicate asset/MAC assignments;
- erased the complete flash;
- wrote the released factory and LittleFS images at offsets taken from the build metadata;
- received esptool verification for both images;
- assigned and read back `BHV Badge NNN` / `BNNN`, or `BHV Admin NNN` / `ANNN`;
- read the configured channels and found exactly `BHV`, then `BHV Info`;
- matched the `BHV Info` PSK fingerprint derived from `userPrefs.jsonc`;
- recorded firmware hashes, node ID, operator, station, port, time, and result.

Audit files are stored under `.local/bhv-flasher/`:

- `events.jsonl` is the append-only attempt and failure history.
- `manifest.csv` is the append-only production-friendly attempt manifest.
- `inventory.json` is the latest successful state of every badge, keyed by hardware MAC.
- `inventory.csv` is the same latest-state inventory in spreadsheet-friendly form.

Each inventory entry records the flash date, hardware MAC, asset ID, assigned long/short badge name, node ID, firmware version
and hashes, and whether the image was an attendee or admin publisher build. A successful `--allow-reflash` updates the latest
inventory entry for that MAC while retaining all older attempts in `events.jsonl` and `manifest.csv`. Pass `--admin` to select
the separately built admin publisher image; attendee is the default.

Channel URLs and raw PSKs are never written to the audit files. The record contains only SHA-256 PSK fingerprints. Back up the records after each production batch.

## Failure and rework behavior

Every non-dry-run attempt creates a record, including failures. A badge that already has a PASS cannot be silently flashed again. Use `--allow-reflash` only at the rework station; the new attempt is appended to the history.

To release an incorrect assignment without deleting its audit history, run:

```sh
.venv/bin/python bin/bhv-flasher.py remove --asset ADMIN-004
```

This appends a `REMOVED` event, deletes the badge from the current inventory, and makes both its asset ID and MAC available again.

`--skip-provision` exists for early hardware testing, but it does not perform the identity or channel readback gates and should not be used for lot acceptance.

The automated result covers firmware and configuration. Display, LEDs, buttons, sensors, channel-0 message exchange, attendee rejection on `BHV Info`, and reception of an admin announcement remain separate functional QA gates.
