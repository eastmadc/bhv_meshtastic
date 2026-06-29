# Biohacking Village DEF CON Badge Firmware

This is a customized fork of [Meshtastic firmware](https://github.com/meshtastic/firmware) for the Biohacking Village DEF CON badge.

We rebooted one of our all-time favorite badges with a new heartbeat: heart-rate and oxygen sensing, animated heartbeat LEDs, and "heart to heart" messages over a private LoRa mesh. It is still Meshtastic at its core, so it works with standard Meshtastic clients and tooling, but this fork adds badge-specific behavior for the Biohacking Village experience.

## What This Firmware Adds

- Heart-rate and SpO2 sensing with MAX3010x pulse oximeter support.
- A heartbeat LED strip that can follow live heart-rate telemetry when a reading is active.
- Custom default, channel, and direct-message color and pulse behavior.
- A hidden text-message command interface for badge personalization.
- A private LoRa network configuration path for event or village deployments.

## Using the Badge

Pair the badge with a Meshtastic client, then use it like a normal Meshtastic node:

- Send channel messages to everyone on the private badge mesh.
- Send direct messages for one-to-one "heart to heart" messages.
- Place a finger on the pulse oximeter sensor to engage heart-rate and oxygen measurement.
- Watch the heartbeat LEDs react to local sensing, incoming messages, and outgoing messages.

The hidden command interface is sent through ordinary Meshtastic text messages. No custom app is required.

## Hidden Command Interface

Commands can start with any of these triggers:

```text
#!
🫀
<3
```

For example, these are equivalent:

```text
#! set default color red blue
🫀 set default color red blue
<3 set default color red blue
```

The command message is consumed by the firmware. Local commands are not sent over LoRa, and over-air commands are handled by the receiving badge instead of showing up as normal chat text.

## Quick Examples

Set your default heartbeat colors:

```text
🫀 set default color red blue
```

Use one color for both halves of the LED strip:

```text
<3 set default color purple
```

Check your current defaults:

```text
#! get default
```

Make the current channel glow amber when messages arrive:

```text
🫀 set ch color amber
```

Set channel 2 to cyan and magenta:

```text
#! set ch 2 color cyan magenta
```

Customize direct-message pulses:

```text
<3 set dm color pink white
<3 set dm notify_pulses 6
```

Ask the badge for help:

```text
#! help
#! help colors
#! help dm
```

## Command Reference

Commands follow this shape:

```text
<trigger> <verb> <scope> [target] [value...]
```

Supported verbs:

- `get`
- `set`
- `clear`
- `list`
- `help`

Supported scopes:

- `default`: badge-wide defaults
- `ch`: channel-specific overrides
- `dm`: direct-message defaults or per-user direct-message overrides
- `hr`: heart-rate sensor controls

The field `led` is accepted as an alias for `color`.

### Defaults

Defaults are used when no channel or DM override is configured.

```text
#! get default
#! get default color
#! set default color <color1> [color2]
#! set default idle_bpm <1-600>
#! set default idle_delay <0-600000>
#! set default notify_pulses <1-20>
#! set default send_pulses <1-20>
```

Defaults:

- `color1=#0000FF`
- `color2=#FF0000`
- `idle_bpm=80`
- `idle_delay=0`
- `notify_pulses=3`
- `send_pulses=1`

### Channel Overrides

Channel commands apply to the active incoming channel unless you include an explicit channel number from `0` through `7`.

```text
#! get ch
#! get ch <n>
#! get ch color
#! set ch color <color1> [color2]
#! set ch <n> color <color1> [color2]
#! set ch notify_pulses <0-20>
#! set ch send_pulses <0-20>
#! clear ch color
#! clear ch <n> color
#! clear ch notify_pulses
#! clear ch send_pulses
```

For channel pulse counts, `0` means "use the default."

### Direct Messages

DM commands configure the direct-message lighting behavior. When sent inside a DM, the badge can store a per-user override for that peer. When sent outside a DM, the command updates the general DM default.

```text
#! get dm
#! get dm color
#! get dm notify_pulses
#! get dm send_pulses
#! set dm color <color1> [color2]
#! set dm notify_pulses <0-20>
#! set dm send_pulses <0-20>
#! clear dm color
#! clear dm notify_pulses
#! clear dm send_pulses
#! clear dm all
#! clear dm <slot>
#! list dm
```

For DM pulse counts, `0` means "use the default." The badge can remember up to 10 per-user DM overrides.

### Heart-Rate Sensor

Heart-rate sensor commands tune the MAX3010x active LED drive used while measuring. Higher sensitivity can help with weak readings, but it also increases sensor brightness and power use. This setting is runtime-only in the current firmware build and returns to the firmware default after reboot.

```text
#! get hr sensitivity
#! set hr sensitivity low
#! set hr sensitivity medium
#! set hr sensitivity high
#! set hr sensitivity default
#! set hr sensitivity <1-79>
```

Sensitivity presets:

- `low`: `31` (`0x1F`)
- `medium` / `default`: `47` (`0x2F`)
- `high`: `79` (`0x4F`)

## Colors

Colors can be named colors or exact hex values in `#RRGGBB` form.

Named colors:

```text
red orange yellow green blue indigo violet purple pink white warmwhite cyan magenta teal lime amber gold off
```

Examples:

```text
#! set default color #FF0000 #0000FF
🫀 set ch color warmwhite
<3 set dm color off pink
```

## Responses

Successful `set` or `clear` commands return `OK ...`. LED color and pulse settings persist immediately; HR sensitivity is runtime-only. `get` commands return the current effective values. Errors are short on purpose, for example:

```text
ERR unknown command; try #! help
ERR invalid color
ERR invalid channel
ERR missing value
ERR too many colors
ERR no active channel
```

## Building

The current local target is Heltec V4:

```bash
uv venv .venv --python 3.10
source .venv/bin/activate
uv pip install --python .venv/bin/python "setuptools<72" platformio
mkdir -p .cache/uv .platformio
export UV_CACHE_DIR="$PWD/.cache/uv"
export PLATFORMIO_CORE_DIR="$PWD/.platformio"
uv run --python .venv/bin/python pio run -e heltec-v4
```

See [README-heltec-v4-setup.md](README-heltec-v4-setup.md) for the fuller local build and flash workflow.

## Upstream

This firmware is based on Meshtastic, an open-source LoRa mesh networking project for long-range, low-power communication without relying on internet or cellular infrastructure.

- [Meshtastic website](https://meshtastic.org)
- [Meshtastic firmware](https://github.com/meshtastic/firmware)
- [Meshtastic docs](https://meshtastic.org/docs/)
