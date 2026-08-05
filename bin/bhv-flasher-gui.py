#!/usr/bin/env python3
"""Three-port Tkinter production station for BHV badges."""

from __future__ import annotations

import argparse
import importlib.util
import os
import queue
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


def configure_tk_environment() -> None:
    """Point uv's relocatable Python at the Tcl/Tk data bundled beside it."""
    library_root = Path(sys.base_prefix) / "lib"
    tcl_library = library_root / "tcl8.6"
    tk_library = library_root / "tk8.6"
    if tcl_library.exists():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_library))
    if tk_library.exists():
        os.environ.setdefault("TK_LIBRARY", str(tk_library))


configure_tk_environment()

import tkinter as tk
from tkinter import messagebox, ttk


ROOT = Path(__file__).resolve().parents[1]
SLOT_COUNT = 3


def load_flasher() -> ModuleType:
    path = ROOT / "bin" / "bhv-flasher.py"
    spec = importlib.util.spec_from_file_location("bhv_flasher_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flasher = load_flasher()


@dataclass
class Slot:
    number: int
    frame: ttk.LabelFrame
    port_var: tk.StringVar
    asset_var: tk.StringVar
    status_var: tk.StringVar
    elapsed_var: tk.StringVar
    port_box: ttk.Combobox
    progress: ttk.Progressbar
    start_button: ttk.Button
    busy: bool = False
    awaiting_disconnect: bool = False
    completed_device: str = ""
    completed_token: str = ""
    started_at: float = 0.0
    reserved_asset: str = ""


class ParallelFlasherApp:
    def __init__(self, root: tk.Tk, *, records_dir: Path, admin_build: bool) -> None:
        self.root = root
        self.records_dir = records_dir.resolve()
        self.messages: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.reserved_assets: set[str] = set()
        self.port_details: dict[str, str] = {}
        self.port_tokens: dict[str, str] = {}
        self.slots: list[Slot] = []

        root.title("BHV Badge Parallel Flasher")
        root.geometry("860x720")
        root.minsize(760, 640)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.admin_var = tk.BooleanVar(value=admin_build)
        self.auto_flash_var = tk.BooleanVar(value=True)
        self.summary_var = tk.StringVar(value="Detecting connected badges…")
        self._build_ui()
        self.refresh_ports()
        self.root.after(100, self._poll_messages)
        self.root.after(250, self._update_elapsed)
        self.root.after(1000, self._auto_scan)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="BHV Badge Production Station", font=("Helvetica", 20, "bold")).pack(
            side="left"
        )
        self.mode_check = ttk.Checkbutton(
            header,
            text="Admin firmware",
            variable=self.admin_var,
            command=self.refresh_asset_previews,
        )
        self.mode_check.pack(side="right", padx=(12, 0))
        ttk.Checkbutton(
            header,
            text="Auto-flash new badges",
            variable=self.auto_flash_var,
        ).pack(side="right", padx=(12, 0))
        ttk.Button(header, text="Refresh Ports", command=self.refresh_ports).pack(side="right")

        ttk.Label(outer, textvariable=self.summary_var).pack(fill="x", pady=(0, 10))

        grid = ttk.Frame(outer)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        for row in range(SLOT_COUNT):
            grid.rowconfigure(row, weight=1)

        for index in range(SLOT_COUNT):
            frame = ttk.LabelFrame(grid, text=f"Slot {index + 1}", padding=12)
            frame.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=(0 if index == 0 else 6, 6 if index < SLOT_COUNT - 1 else 0),
            )
            frame.columnconfigure(1, weight=1)

            port_var = tk.StringVar()
            asset_var = tk.StringVar(value="—")
            status_var = tk.StringVar(value="No badge port selected")
            elapsed_var = tk.StringVar(value="")

            ttk.Label(frame, text="USB port").grid(row=0, column=0, sticky="w", padx=(0, 8))
            port_box = ttk.Combobox(frame, textvariable=port_var, state="readonly")
            port_box.grid(row=0, column=1, columnspan=2, sticky="ew")

            ttk.Label(frame, text="Badge ID").grid(row=1, column=0, sticky="w", pady=(12, 0))
            ttk.Label(frame, textvariable=asset_var, font=("Menlo", 17, "bold")).grid(
                row=1, column=1, sticky="w", pady=(12, 0)
            )
            ttk.Label(frame, textvariable=elapsed_var).grid(row=1, column=2, sticky="e", pady=(12, 0))

            progress = ttk.Progressbar(frame, mode="indeterminate")
            progress.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 8))

            ttk.Label(frame, textvariable=status_var, wraplength=390).grid(
                row=3, column=0, columnspan=2, sticky="w"
            )
            start_button = ttk.Button(frame, text="Flash This Slot")
            start_button.grid(row=3, column=2, sticky="e", padx=(8, 0))

            slot = Slot(
                number=index + 1,
                frame=frame,
                port_var=port_var,
                asset_var=asset_var,
                status_var=status_var,
                elapsed_var=elapsed_var,
                port_box=port_box,
                progress=progress,
                start_button=start_button,
            )
            start_button.configure(command=lambda selected=slot: self.start_slots([selected]))
            port_box.bind(
                "<<ComboboxSelected>>",
                lambda _event, selected=slot: self._port_selected(selected),
            )
            self.slots.append(slot)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(14, 0))
        ttk.Label(footer, text=f"Records: {self.records_dir}").pack(side="left")
        self.start_all_button = ttk.Button(footer, text="Flash All Connected", command=self.start_all)
        self.start_all_button.pack(side="right")

    def candidate_ports(self) -> list[Any]:
        ports = [port for port in flasher.list_serial_ports() if port.likely_badge]
        callout = [port for port in ports if port.device.startswith("/dev/cu.")]
        return sorted(callout or ports, key=lambda port: (port.location or "", port.device))

    @staticmethod
    def port_label(port: Any) -> str:
        identity = port.serial_number or port.location or port.description
        return f"{port.device}  [{identity}]" if identity else port.device

    @staticmethod
    def port_token(port: Any) -> str:
        return port.serial_number or port.hwid or port.location or port.device

    def refresh_ports(self, *, show_errors: bool = True) -> None:
        try:
            ports = self.candidate_ports()
        except Exception as exc:
            if show_errors:
                messagebox.showerror("Port detection failed", str(exc), parent=self.root)
            else:
                self.summary_var.set(f"Port scan failed: {exc}")
            return

        previous_devices = [self._device_from_label(slot.port_var.get()) for slot in self.slots]
        labels = [self.port_label(port) for port in ports]
        self.port_details = {label: port.device for label, port in zip(labels, ports)}
        self.port_tokens = {port.device: self.port_token(port) for port in ports}
        by_device = {port.device: label for label, port in zip(labels, ports)}
        newly_detected: list[Slot] = []

        used: set[str] = {
            previous_devices[index]
            for index, slot in enumerate(self.slots)
            if slot.busy and previous_devices[index]
        }
        for index, slot in enumerate(self.slots):
            slot.port_box.configure(values=labels)
            previous = previous_devices[index]
            if slot.busy:
                if previous in by_device:
                    slot.port_var.set(by_device[previous])
                continue

            if slot.awaiting_disconnect and previous == slot.completed_device:
                if (
                    previous in by_device
                    and self.port_tokens.get(previous) == slot.completed_token
                ):
                    slot.port_var.set(by_device[previous])
                    used.add(previous)
                    continue
                slot.awaiting_disconnect = False
                slot.completed_device = ""
                slot.completed_token = ""
                replacement_detected = previous in by_device
                if previous not in by_device:
                    slot.port_var.set("")
                    slot.asset_var.set("—")
                    slot.status_var.set("Previous badge disconnected; waiting for next badge")
            else:
                replacement_detected = False

            if previous in by_device and previous not in used:
                selected = by_device[previous]
            else:
                selected = next(
                    (label for label in labels if self.port_details[label] not in used),
                    "",
                )
            changed = self._device_from_label(selected) != previous
            slot.port_var.set(selected)
            if selected:
                used.add(self.port_details[selected])
                if changed or slot.status_var.get() in ("No badge detected", "Waiting for badge"):
                    slot.status_var.set("Badge detected — ready")
                slot.start_button.configure(state="normal")
                if changed or replacement_detected:
                    newly_detected.append(slot)
            else:
                slot.status_var.set("Waiting for badge")
                slot.start_button.configure(state="disabled")

        self.summary_var.set(
            f"Detected {len(ports)} badge port{'s' if len(ports) != 1 else ''}. "
            "Open slots rescan automatically every second."
        )
        self.refresh_asset_previews()
        ports_valid = self._validate_ports()
        if self.auto_flash_var.get() and ports_valid and newly_detected:
            self.start_slots(newly_detected)

    def _auto_scan(self) -> None:
        self.refresh_ports(show_errors=False)
        self.root.after(1000, self._auto_scan)

    def _device_from_label(self, label: str) -> str:
        if label in self.port_details:
            return self.port_details[label]
        return label.split("  [", 1)[0] if label else ""

    def _validate_ports(self) -> bool:
        selected = [
            self._device_from_label(slot.port_var.get())
            for slot in self.slots
            if slot.port_var.get()
        ]
        duplicates = {device for device in selected if selected.count(device) > 1}
        for slot in self.slots:
            device = self._device_from_label(slot.port_var.get())
            if not slot.busy and device in duplicates:
                slot.status_var.set("Select a unique USB port")
        return not duplicates

    def _port_selected(self, slot: Slot) -> None:
        device = self._device_from_label(slot.port_var.get())
        token = self.port_tokens.get(device, "")
        if slot.awaiting_disconnect and (
            device != slot.completed_device or token != slot.completed_token
        ):
            slot.awaiting_disconnect = False
            slot.completed_device = ""
            slot.completed_token = ""
            slot.status_var.set("Badge detected — ready")
            slot.start_button.configure(state="normal")
        self._validate_ports()
        self.refresh_asset_previews()
        if self.auto_flash_var.get() and not slot.awaiting_disconnect:
            self.start_slots([slot])

    def refresh_asset_previews(self) -> None:
        try:
            idle = [
                slot
                for slot in self.slots
                if not slot.busy and not slot.awaiting_disconnect
            ]
            assets = flasher.next_available_assets(
                flasher.read_events(self.records_dir),
                admin_build=self.admin_var.get(),
                count=len(idle),
                reserved=self.reserved_assets,
            )
            for slot, asset in zip(idle, assets):
                long_name, short_name = flasher.badge_names(
                    asset, admin_build=self.admin_var.get()
                )
                slot.asset_var.set(asset)
                if slot.port_var.get():
                    if not slot.status_var.get().startswith("FAIL"):
                        slot.status_var.set(f"Ready: {long_name} / {short_name}")
        except Exception as exc:
            self.summary_var.set(str(exc))

    def start_all(self) -> None:
        self.start_slots(
            [
                slot
                for slot in self.slots
                if slot.port_var.get() and not slot.busy and not slot.awaiting_disconnect
            ]
        )

    def start_slots(self, targets: list[Slot]) -> None:
        targets = [
            slot
            for slot in targets
            if not slot.busy and not slot.awaiting_disconnect and slot.port_var.get()
        ]
        if not targets:
            messagebox.showinfo("No available slots", "Connect or select at least one badge port.")
            return
        if not self._validate_ports():
            messagebox.showerror("Duplicate ports", "Each active slot must use a different USB port.")
            return

        selected_devices = [self._device_from_label(slot.port_var.get()) for slot in targets]
        busy_devices = {
            self._device_from_label(slot.port_var.get()) for slot in self.slots if slot.busy
        }
        if any(device in busy_devices for device in selected_devices):
            messagebox.showerror("Port busy", "One of the selected USB ports is already flashing.")
            return

        admin_build = self.admin_var.get()
        try:
            flasher.load_release_artifacts(admin_build)
            assets = flasher.next_available_assets(
                flasher.read_events(self.records_dir),
                admin_build=admin_build,
                count=len(targets),
                reserved=self.reserved_assets,
            )
        except Exception as exc:
            messagebox.showerror("Cannot start batch", str(exc), parent=self.root)
            return

        self.mode_check.configure(state="disabled")
        for slot, asset in zip(targets, assets):
            self._start_slot(slot, asset, admin_build)
        self._update_controls()

    def _start_slot(self, slot: Slot, asset: str, admin_build: bool) -> None:
        port = self._device_from_label(slot.port_var.get())
        slot.busy = True
        slot.started_at = time.monotonic()
        slot.reserved_asset = asset
        self.reserved_assets.add(asset)
        slot.asset_var.set(asset)
        slot.status_var.set("Queued")
        slot.elapsed_var.set("0:00")
        slot.progress.start(12)
        slot.start_button.configure(state="disabled")
        slot.port_box.configure(state="disabled")

        args = argparse.Namespace(
            port=port,
            baud=921600,
            boot_wait=12,
            api_timeout=45,
            skip_provision=False,
            expected_channel=list(flasher.DEFAULT_CHANNELS),
            records_dir=self.records_dir,
            station=socket.gethostname(),
            operator=os.environ.get("USER", "unknown"),
            admin_build=admin_build,
            allow_reflash=False,
            dry_run=False,
            build_type="admin" if admin_build else "attendee",
            progress_callback=lambda phase, detail: self.messages.put(
                ("progress", slot.number, phase, detail)
            ),
        )

        def worker() -> None:
            try:
                passed = flasher.flash_one(args, asset)
                error = getattr(args, "last_error", "")
            except Exception as exc:
                passed = False
                error = str(exc)
            self.messages.put(("done", slot.number, passed, error, asset))

        threading.Thread(target=worker, name=f"bhv-flash-slot-{slot.number}", daemon=True).start()

    def _poll_messages(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                kind, slot_number = message[:2]
                slot = self.slots[slot_number - 1]
                if kind == "progress":
                    _kind, _number, _phase, detail = message
                    slot.status_var.set(detail)
                elif kind == "done":
                    _kind, _number, passed, error, asset = message
                    slot.progress.stop()
                    slot.busy = False
                    slot.awaiting_disconnect = True
                    slot.completed_device = self._device_from_label(slot.port_var.get())
                    slot.completed_token = self.port_tokens.get(slot.completed_device, "")
                    slot.elapsed_var.set(self._elapsed_text(slot.started_at))
                    slot.status_var.set(
                        f"PASS — {asset}. Disconnect badge."
                        if passed
                        else f"FAIL — {error or 'Unknown flashing error'}"
                    )
                    slot.start_button.configure(state="disabled")
                    slot.port_box.configure(state="readonly")
                    self.reserved_assets.discard(slot.reserved_asset)
                    slot.reserved_asset = ""
                    self._update_controls()
                    if not any(item.busy for item in self.slots):
                        self.mode_check.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    @staticmethod
    def _elapsed_text(started_at: float) -> str:
        elapsed = max(0, int(time.monotonic() - started_at))
        return f"{elapsed // 60}:{elapsed % 60:02d}"

    def _update_elapsed(self) -> None:
        for slot in self.slots:
            if slot.busy:
                slot.elapsed_var.set(self._elapsed_text(slot.started_at))
        self.root.after(250, self._update_elapsed)

    def _update_controls(self) -> None:
        has_ready = any(
            slot.port_var.get() and not slot.busy and not slot.awaiting_disconnect
            for slot in self.slots
        )
        self.start_all_button.configure(state="normal" if has_ready else "disabled")

    def close(self) -> None:
        if any(slot.busy for slot in self.slots):
            if not messagebox.askyesno(
                "Flashing in progress",
                "Badges are still flashing. Close the window anyway?",
                parent=self.root,
            ):
                return
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", action="store_true", help="Start in admin-publisher mode")
    parser.add_argument("--records-dir", type=Path, default=flasher.DEFAULT_RECORDS_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = tk.Tk()
    ParallelFlasherApp(root, records_dir=args.records_dir, admin_build=args.admin)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
