# Local Setup and Build for Heltec V4 (uv + .venv)

This guide shows a local build workflow for:

- `heltec-v4` (OLED)
- `heltec-v4-tft` (TFT)

All commands are run from the repository root.

## Prerequisites

- `uv` installed
- Git
- macOS or Linux shell

## 1. Create a local Python virtual environment

```bash
uv venv .venv --python 3.10
source .venv/bin/activate
uv pip install --python .venv/bin/python "setuptools<72" platformio
```

## 2. Keep build/cache data local to this repo (recommended)

```bash
mkdir -p .cache/uv .platformio
export UV_CACHE_DIR="$PWD/.cache/uv"
export PLATFORMIO_CORE_DIR="$PWD/.platformio"
```

This avoids writing to `~/.cache/uv` and `~/.platformio`.

## 3. Build firmware

Heltec V4 (OLED):

```bash
uv run --python .venv/bin/python pio run -e heltec-v4
```

Heltec V4 TFT:

```bash
uv run --python .venv/bin/python pio run -e heltec-v4-tft
```

## 4. Build outputs

For `heltec-v4`, artifacts are created in:

`./.pio/build/heltec-v4/`

Key files:

- `firmware-heltec-v4-<version>.bin`
- `firmware-heltec-v4-<version>.factory.bin`
- `firmware-heltec-v4-<version>.elf`
- `littlefs-heltec-v4-<version>.bin`

## 5. Flash over USB (optional)

```bash
uv run --python .venv/bin/python pio run -e heltec-v4 -t upload --upload-port <PORT>
```

Examples:

- macOS: `/dev/cu.usbmodem*`
- Linux: `/dev/ttyACM0` or `/dev/ttyUSB0`

## 6. Serial monitor (optional)

```bash
uv run --python .venv/bin/python pio device monitor -b 115200 -p <PORT>
```

## Troubleshooting

If dependencies cannot download:

- Check internet access and rerun the build.

If you see permission errors under `~/.platformio`:

- Make sure `PLATFORMIO_CORE_DIR="$PWD/.platformio"` is set.

If you hit:

`'mbedtls_strerror' was not declared in this scope` from `esp32_https_server`

- Edit `./.pio/libdeps/heltec-v4/esp32_https_server/src/HTTPSConnection.cpp`
- Add this include near the top:

```cpp
#include "mbedtls/error.h"
```

- Re-run:

```bash
uv run --python .venv/bin/python pio run -e heltec-v4
```
