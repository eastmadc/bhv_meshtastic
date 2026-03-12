#!/usr/bin/env python3
"""
Convert a source image into USERPREFS_OEM_IMAGE_* values for the Heltec V4 OLED.

This performs a literal grayscale -> hard-threshold -> 1-bit conversion using ffmpeg,
then packs the pixels row-by-row in the bit order expected by drawXbm().
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "command failed")


def ffmpeg_to_pgm(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    threshold: int,
    invert: bool,
    pad_left: int,
    pad_top: int,
    pad_right: int,
    pad_bottom: int,
) -> None:
    # Preserve aspect ratio, fit inside the drawable box, then pad to exact dimensions.
    inner_width = width - pad_left - pad_right
    inner_height = height - pad_top - pad_bottom
    if inner_width <= 0 or inner_height <= 0:
        raise ValueError("padding leaves no drawable area")

    # Apply a hard threshold after conversion to grayscale.
    invert_expr = "255-lum(X,Y)" if invert else "lum(X,Y)"
    threshold_expr = f"if(gt({invert_expr},{threshold}),255,0)"
    vf = (
        f"scale={inner_width}:{inner_height}:force_original_aspect_ratio=decrease:flags=neighbor,"
        f"pad={width}:{height}:{pad_left}+({inner_width}-iw)/2:{pad_top}+({inner_height}-ih)/2:color=black,"
        f"format=gray,"
        f"geq=lum_expr='{threshold_expr}'"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            vf,
            str(dst),
        ]
    )


def ffmpeg_preview(src: Path, dst: Path, scale: int) -> None:
    vf = f"scale=iw*{scale}:ih*{scale}:flags=neighbor"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            vf,
            str(dst),
        ]
    )


def read_pgm(path: Path) -> tuple[int, int, list[int]]:
    data = path.read_bytes()
    if not data.startswith(b"P5"):
        raise ValueError("expected raw PGM (P5)")

    i = 2  # Skip the P5 magic.
    tokens: list[bytes] = []

    while len(tokens) < 3:
        while i < len(data) and data[i] in b" \t\r\n":
            i += 1
        if i >= len(data):
            raise ValueError("unexpected EOF in PGM header")
        if data[i] == 0x23:  # '#'
            while i < len(data) and data[i] != 0x0A:
                i += 1
            continue

        start = i
        while i < len(data) and data[i] not in b" \t\r\n":
            i += 1
        tokens.append(data[start:i])

    while i < len(data) and data[i] in b" \t\r\n":
        i += 1

    width = int(tokens[0])
    height = int(tokens[1])
    maxval = int(tokens[2])
    if maxval != 255:
        raise ValueError(f"unsupported maxval {maxval}")

    pixels = list(data[i : i + (width * height)])
    if len(pixels) != width * height:
        raise ValueError("truncated pixel data")
    return width, height, pixels


def pack_xbm(width: int, height: int, pixels: list[int]) -> list[int]:
    packed: list[int] = []
    bytes_per_row = (width + 7) // 8
    for y in range(height):
        for byte_index in range(bytes_per_row):
            value = 0
            for bit in range(8):
                x = byte_index * 8 + bit
                if x >= width:
                    continue
                pixel = pixels[(y * width) + x]
                if pixel >= 128:
                    value |= 1 << bit
            packed.append(value)
    return packed


def format_cpp_bytes(values: list[int]) -> str:
    return "{ " + ", ".join(f"0x{value:02X}" for value in values) + " }"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", type=Path, help="source image path")
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--height", type=int, default=64)
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--preview", type=Path, help="optional preview PNG path for the thresholded bitmap")
    parser.add_argument("--preview-scale", type=int, default=8, help="preview upscale factor")
    parser.add_argument("--pad-left", type=int, default=0)
    parser.add_argument("--pad-top", type=int, default=0)
    parser.add_argument("--pad-right", type=int, default=0)
    parser.add_argument("--pad-bottom", type=int, default=0)
    args = parser.parse_args()

    if not args.src.exists():
        print(f"missing source image: {args.src}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmpdir:
        pgm_path = Path(tmpdir) / "logo.pgm"
        ffmpeg_to_pgm(
            args.src,
            pgm_path,
            args.width,
            args.height,
            args.threshold,
            args.invert,
            args.pad_left,
            args.pad_top,
            args.pad_right,
            args.pad_bottom,
        )
        if args.preview:
            args.preview.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg_preview(pgm_path, args.preview, max(1, args.preview_scale))
        width, height, pixels = read_pgm(pgm_path)
        packed = pack_xbm(width, height, pixels)

    print(f'"USERPREFS_OEM_IMAGE_WIDTH": "{width}",')
    print(f'"USERPREFS_OEM_IMAGE_HEIGHT": "{height}",')
    print(f'"USERPREFS_OEM_IMAGE_DATA": "{format_cpp_bytes(packed)}",')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
