# BHV production firmware

Run these commands from the repository root to populate the release folders:

```sh
.venv/bin/python bin/bhv-flasher.py build
.venv/bin/python bin/bhv-flasher.py build --admin
```

- `attendee/` is the default image used by `bhv-flasher.py flash` and cannot publish to `BHV Info`.
- `admin/` is selected by `bhv-flasher.py flash --admin` and can publish to `BHV Info`.

Copy this entire directory to each flashing station. Each release manifest pins the exact factory image, filesystem image,
firmware target, SHA-256 hashes, and expected `BHV Info` fingerprint.
