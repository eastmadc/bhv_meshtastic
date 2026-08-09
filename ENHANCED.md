# BHV badge — enhanced build notes

Notes for an experimental build of the BHV badge firmware that adds a **consensual,
opt‑in "injector" mode** to the hidden `#!`/`<3`/🫀 LED command protocol, plus a
**security fix** that makes over‑the‑air LED commands safe by default.

Everything here is **off by default** — a normal `heltec-v4-admin` build is unchanged.

## The two changes

| Flag (default) | Effect |
| --- | --- |
| `USERPREFS_BHV_INJECTOR` (0) | When on, a `#!` command typed on **this** badge's own client is applied + acked locally **and** broadcast over the mesh, so opted‑in badges apply it too. For coordinated light shows. |
| `USERPREFS_BHV_ACCEPT_OVER_AIR_LED` (0) | When on, this badge **accepts** over‑air `#!` mutations. When off (default), over‑air `set`/`clear` are ignored (`get`/`help` still work). |

Together they form a **consent model**: injection only affects badges that both (a) hear
an injector and (b) opted in to accepting over‑air commands. With both flags off — the
default — the badge behaves exactly like upstream, and the previous "any node on the
channel can silently reconfigure every badge" behavior is closed.

### Files touched
- `src/mesh/MeshService.cpp` — `handleToRadio`: opt‑in broadcast of a locally‑entered command.
- `src/led/LocalLedConfig.cpp` — `handleCommand`: honor `local_client_origin`; drop over‑air mutations unless opted in.

Both are small, guarded blocks; the local `OK/ERR` ack path is preserved in all builds.

## Building

```bash
# default (upstream behavior)
pio run -e heltec-v4-admin

# injector badge (sends) — for the person driving a show
PLATFORMIO_BUILD_FLAGS="-DUSERPREFS_BHV_INJECTOR=1" pio run -e heltec-v4-admin

# participant badge (accepts) — for opted-in crew
PLATFORMIO_BUILD_FLAGS="-DUSERPREFS_BHV_ACCEPT_OVER_AIR_LED=1" pio run -e heltec-v4-admin
```

Build note: on a bare host the factory‑bin post step needs the `intelhex` module
(`pip install intelhex`) since it's imported by the bundled esptool.

## Flashing without losing a provisioned badge's identity

To swap only the app while keeping a badge's NVS (identity, channels, keys) and prefs:

```bash
esptool --chip esp32s3 write_flash 0x10000 \
  .pio/build/heltec-v4-admin/firmware-heltec-v4-admin-<ver>.bin
# (no erase_flash; app0 lives at 0x10000, nvs at 0x9000, prefs/spiffs at 0xc90000)
```

Always take a full backup first (`esptool read_flash 0 0x1000000 backup.bin`) and revert
with `esptool write_flash 0x0 backup.bin`.

## Security

The default‑on behavior of the over‑air command path (mutations applied without checking
origin) was reported privately to the maintainer. The change in `LocalLedConfig.cpp`
above is the proposed fix. Please do not enable `USERPREFS_BHV_ACCEPT_OVER_AIR_LED` on
badges handed to attendees without their awareness.
