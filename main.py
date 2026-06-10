"""
main.py — Apple Health Export → CSV Converter
A standalone Windows desktop application.

Select your Apple Health export folder and this tool will convert
the large export.xml into organized CSV files ready for analysis.
"""

import sys
import os
import time
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ── Colour palette ─────────────────────────────────────────────────────────
BG_DARK       = "#0f1117"
BG_CARD       = "#1a1d2e"
BG_CARD2      = "#1e2235"
ACCENT        = "#ff375f"   # Apple Health red
ACCENT2       = "#30d158"   # Apple green (success)
ACCENT_BLUE   = "#0a84ff"   # Apple blue (progress)
TEXT_PRIMARY  = "#f2f2f7"
TEXT_SECONDARY= "#8e8e93"
TEXT_MUTED    = "#48484a"
BORDER        = "#2c2c2e"
FONT_FAMILY   = "Segoe UI"

APP_VERSION   = "1.0.0"
APP_TITLE     = "Apple Health → CSV Converter"


class AppleHealthConverter(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.configure(bg=BG_DARK)
        self.resizable(False, False)

        # Center window
        w, h = 680, 620
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        # State
        self._selected_folder: Path | None = None
        self._running = False
        self._cancel_requested = False
        self._start_time = 0.0

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=BG_DARK, pady=0)
        header.pack(fill="x", padx=0, pady=0)

        # Top accent bar
        accent_bar = tk.Frame(self, bg=ACCENT, height=3)
        accent_bar.pack(fill="x")

        # Logo + title row
        title_frame = tk.Frame(self, bg=BG_DARK)
        title_frame.pack(fill="x", padx=28, pady=(20, 0))

        # Heart icon (unicode)
        heart = tk.Label(
            title_frame, text="♥", font=(FONT_FAMILY, 28), bg=BG_DARK, fg=ACCENT
        )
        heart.pack(side="left", pady=(0, 4))

        title_text = tk.Frame(title_frame, bg=BG_DARK)
        title_text.pack(side="left", padx=10)

        tk.Label(
            title_text,
            text=APP_TITLE,
            font=(FONT_FAMILY, 16, "bold"),
            bg=BG_DARK,
            fg=TEXT_PRIMARY,
        ).pack(anchor="w")

        tk.Label(
            title_text,
            text="Convert your Apple Health export to analysis-ready CSV files",
            font=(FONT_FAMILY, 9),
            bg=BG_DARK,
            fg=TEXT_SECONDARY,
        ).pack(anchor="w")

        # ── Divider ──
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=28, pady=16)

        # ── Folder Selection Card ──
        card = tk.Frame(self, bg=BG_CARD, bd=0, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill="x", padx=28, pady=0)

        tk.Label(
            card,
            text="STEP 1 — SELECT YOUR EXPORT FOLDER",
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=TEXT_MUTED,
            pady=0,
        ).pack(anchor="w", padx=16, pady=(14, 6))

        tk.Label(
            card,
            text=(
                "Point to the unzipped apple_health_export folder from your iPhone.\n"
                "It should contain export.xml (the main health database)."
            ),
            font=(FONT_FAMILY, 9),
            bg=BG_CARD,
            fg=TEXT_SECONDARY,
            justify="left",
            wraplength=580,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        folder_row = tk.Frame(card, bg=BG_CARD)
        folder_row.pack(fill="x", padx=16, pady=(0, 16))

        self._folder_var = tk.StringVar(value="No folder selected")
        self._folder_label = tk.Label(
            folder_row,
            textvariable=self._folder_var,
            font=(FONT_FAMILY, 9),
            bg=BG_CARD2,
            fg=TEXT_SECONDARY,
            anchor="w",
            padx=10,
            pady=8,
            width=52,
            wraplength=440,
        )
        self._folder_label.pack(side="left", fill="x", expand=True)

        self._browse_btn = tk.Button(
            folder_row,
            text="  Browse…  ",
            font=(FONT_FAMILY, 9, "bold"),
            bg=ACCENT_BLUE,
            fg="white",
            activebackground="#0070e0",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=8,
            bd=0,
            command=self._browse_folder,
        )
        self._browse_btn.pack(side="left", padx=(8, 0))

        # ── Validation status ──
        self._validation_var = tk.StringVar(value="")
        self._validation_label = tk.Label(
            self,
            textvariable=self._validation_var,
            font=(FONT_FAMILY, 9),
            bg=BG_DARK,
            fg=TEXT_SECONDARY,
        )
        self._validation_label.pack(anchor="w", padx=28, pady=(8, 0))

        # ── Convert Button ──
        self._convert_btn = tk.Button(
            self,
            text="⚡  Convert to CSV",
            font=(FONT_FAMILY, 13, "bold"),
            bg=ACCENT,
            fg="white",
            activebackground="#cc2d4a",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=0,
            pady=14,
            bd=0,
            state="disabled",
            command=self._start_conversion,
        )
        self._convert_btn.pack(fill="x", padx=28, pady=16)

        # ── Progress area ──
        prog_card = tk.Frame(self, bg=BG_CARD, bd=0, highlightthickness=1,
                             highlightbackground=BORDER)
        prog_card.pack(fill="x", padx=28, pady=0)

        prog_header = tk.Frame(prog_card, bg=BG_CARD)
        prog_header.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(
            prog_header,
            text="STEP 2 — PROGRESS",
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=TEXT_MUTED,
        ).pack(side="left")

        self._elapsed_var = tk.StringVar(value="")
        tk.Label(
            prog_header,
            textvariable=self._elapsed_var,
            font=(FONT_FAMILY, 8),
            bg=BG_CARD,
            fg=TEXT_MUTED,
        ).pack(side="right")

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure(
            "Health.Horizontal.TProgressbar",
            troughcolor=BG_CARD2,
            background=ACCENT_BLUE,
            bordercolor=BG_CARD,
            lightcolor=ACCENT_BLUE,
            darkcolor=ACCENT_BLUE,
            thickness=8,
        )

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            prog_card,
            variable=self._progress_var,
            maximum=100,
            mode="indeterminate",
            style="Health.Horizontal.TProgressbar",
            length=580,
        )
        self._progress_bar.pack(padx=16, pady=(4, 8))

        # Status text
        self._status_var = tk.StringVar(value="Waiting for folder selection…")
        self._status_label = tk.Label(
            prog_card,
            textvariable=self._status_var,
            font=(FONT_FAMILY, 9),
            bg=BG_CARD,
            fg=TEXT_SECONDARY,
            anchor="w",
            wraplength=600,
        )
        self._status_label.pack(anchor="w", padx=16, pady=(0, 4))

        # Stats row
        stats_row = tk.Frame(prog_card, bg=BG_CARD)
        stats_row.pack(fill="x", padx=16, pady=(0, 14))

        self._rec_var   = tk.StringVar(value="Records: —")
        self._types_var = tk.StringVar(value="Types: —")
        self._work_var  = tk.StringVar(value="Workouts: —")

        for var in (self._rec_var, self._types_var, self._work_var):
            tk.Label(
                stats_row,
                textvariable=var,
                font=(FONT_FAMILY, 9),
                bg=BG_CARD,
                fg=TEXT_MUTED,
            ).pack(side="left", padx=(0, 24))

        # ── Output area (initially hidden) ──
        self._output_frame = tk.Frame(self, bg=BG_DARK)
        self._output_frame.pack(fill="x", padx=28, pady=12)

        self._output_var = tk.StringVar(value="")
        self._output_label = tk.Label(
            self._output_frame,
            textvariable=self._output_var,
            font=(FONT_FAMILY, 9),
            bg=BG_DARK,
            fg=ACCENT2,
            anchor="w",
            wraplength=620,
            justify="left",
        )
        self._output_label.pack(anchor="w")

        self._open_btn = tk.Button(
            self._output_frame,
            text="📂  Open Output Folder",
            font=(FONT_FAMILY, 9),
            bg=BG_CARD2,
            fg=TEXT_PRIMARY,
            activebackground=BORDER,
            activeforeground=TEXT_PRIMARY,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
            bd=0,
            command=self._open_output,
        )
        # (packed only on success)

        # ── Footer ──
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=28, pady=(8, 0))
        tk.Label(
            self,
            text=f"v{APP_VERSION}  •  Processes data locally, nothing leaves your machine",
            font=(FONT_FAMILY, 8),
            bg=BG_DARK,
            fg=TEXT_MUTED,
        ).pack(pady=8)

    # ── Event Handlers ──────────────────────────────────────────────────────

    def _browse_folder(self):
        folder = filedialog.askdirectory(
            title="Select your apple_health_export folder",
            mustexist=True,
        )
        if not folder:
            return

        path = Path(folder)
        self._selected_folder = path

        # Truncate display path if too long
        display = str(path)
        if len(display) > 60:
            display = "…" + display[-57:]
        self._folder_var.set(display)

        # Validate
        self._validate_folder(path)

    def _validate_folder(self, path: Path):
        xml_path = path / "export.xml"
        cda_path = path / "export_cda.xml"

        if not xml_path.exists():
            self._validation_var.set("⚠  export.xml not found — is this the right folder?")
            self._validation_label.configure(fg="#ff9f0a")
            self._convert_btn.configure(state="disabled")
            return

        # Get file size
        try:
            size_gb = xml_path.stat().st_size / (1024 ** 3)
            size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{xml_path.stat().st_size / (1024**2):.0f} MB"
        except Exception:
            size_str = "unknown size"

        extras = []
        if cda_path.exists():
            extras.append("clinical records")
        gpx_count = len(list(path.glob("**/*.gpx")))
        if gpx_count:
            extras.append(f"{gpx_count} GPX workout routes")
        ecg_count = len(list(path.glob("**/*.csv")))
        if ecg_count:
            extras.append(f"{ecg_count} ECG files")

        extra_str = f"  +  {', '.join(extras)}" if extras else ""
        self._validation_var.set(f"✓  export.xml found ({size_str}){extra_str}")
        self._validation_label.configure(fg=ACCENT2)
        self._convert_btn.configure(state="normal")
        self._status_var.set("Ready — click Convert to begin.")

    def _start_conversion(self):
        if self._running:
            return
        if not self._selected_folder:
            return

        self._running = True
        self._cancel_requested = False
        self._start_time = time.time()

        # Update UI
        self._browse_btn.configure(state="disabled")
        self._convert_btn.configure(state="disabled", text="Converting…")
        self._progress_bar.configure(mode="indeterminate")
        self._progress_bar.start(12)
        self._output_var.set("")
        try:
            self._open_btn.pack_forget()
        except Exception:
            pass

        # Start conversion in background thread
        t = threading.Thread(target=self._run_conversion, daemon=True)
        t.start()

        # Start elapsed timer
        self._tick_elapsed()

    def _tick_elapsed(self):
        if self._running:
            elapsed = time.time() - self._start_time
            m, s = divmod(int(elapsed), 60)
            self._elapsed_var.set(f"Elapsed: {m:02d}:{s:02d}")
            self.after(1000, self._tick_elapsed)

    def _run_conversion(self):
        """Background thread: run the parser."""
        try:
            from writers import OutputManager
            from parser import parse_export

            output_mgr = OutputManager(self._selected_folder)

            def on_progress(total, current_type):
                short = current_type.replace("HKQuantityTypeIdentifier", "").replace(
                    "HKCategoryTypeIdentifier", ""
                )
                self.after(0, lambda: self._update_progress(total, short, output_mgr))

            def cancel_check():
                return self._cancel_requested

            self.after(0, lambda: self._status_var.set("Parsing export.xml — this may take several minutes for large exports…"))

            stats = parse_export(
                export_folder=self._selected_folder,
                output_manager=output_mgr,
                progress_callback=on_progress,
                cancel_check=cancel_check,
            )

            self.after(0, lambda: self._status_var.set("Finalizing CSV files and writing summary…"))
            summary_path = output_mgr.close_and_write_summary()

            self.after(0, lambda: self._on_success(stats, summary_path))

        except Exception as e:
            self.after(0, lambda: self._on_error(str(e)))

    def _update_progress(self, total: int, current_type: str, mgr):
        self._status_var.set(f"Processing: {current_type}…")
        self._rec_var.set(f"Records: {total:,}")
        self._types_var.set(f"Types: {mgr.type_count()}")
        self._work_var.set(f"Workouts: {mgr.workout_count:,}")

    def _on_success(self, stats: dict, summary_path: Path):
        self._running = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(100)

        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)

        # Final stats
        total = stats["total_records"]
        types = stats["record_types"]
        workouts = stats["workouts"]
        activity = stats["activity_summaries"]
        errors = stats["errors"]

        self._rec_var.set(f"Records: {total:,}")
        self._types_var.set(f"Types: {types}")
        self._work_var.set(f"Workouts: {workouts:,}")

        style_ok = {"fg": ACCENT2}
        self._status_label.configure(**style_ok)
        self._status_var.set(
            f"✓ Complete in {m}m {s}s  —  "
            f"{total:,} health records  ·  {types} metric types  ·  "
            f"{workouts:,} workouts  ·  {activity:,} activity days"
            + (f"  ·  {errors} parse warnings" if errors else "")
        )

        out_dir = summary_path.parent
        self._output_var.set(
            f"Output folder: {out_dir}\n"
            f"{types + (3 if workouts else 0)} CSV files written."
        )
        self._open_btn.pack(anchor="w", pady=(6, 0))
        self._output_folder_path = out_dir

        # Re-enable UI
        self._browse_btn.configure(state="normal")
        self._convert_btn.configure(state="normal", text="⚡  Convert Again")

    def _on_error(self, message: str):
        self._running = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(0)

        self._status_label.configure(fg=ACCENT)
        self._status_var.set(f"✗ Error: {message}")

        self._browse_btn.configure(state="normal")
        self._convert_btn.configure(state="normal", text="⚡  Convert to CSV")

        messagebox.showerror(
            "Conversion Error",
            f"An error occurred during conversion:\n\n{message}\n\n"
            "Please check that the export folder is valid and not corrupted.",
        )

    def _open_output(self):
        if hasattr(self, "_output_folder_path") and self._output_folder_path.exists():
            os.startfile(str(self._output_folder_path))


if __name__ == "__main__":
    app = AppleHealthConverter()
    app.mainloop()
