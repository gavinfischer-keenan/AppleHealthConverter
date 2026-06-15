"""
main.py — Apple Health Export → CSV Converter  v1.1
A standalone Windows desktop application.

v1.2 additions:
  - "Last 3 Months" and "Last 6 Months" quick-export buttons
  - "Last 1 Month" and "Last 2 Months" quick-export buttons
  - All output files auto-split at 10 MB into part1, part2, …
"""

import os
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ── Colour palette ─────────────────────────────────────────────────────────
BG_DARK        = "#0f1117"
BG_CARD        = "#1a1d2e"
BG_CARD2       = "#1e2235"
ACCENT         = "#ff375f"   # Apple Health red
ACCENT2        = "#30d158"   # Apple green (success)
ACCENT_BLUE    = "#0a84ff"   # Apple blue
ACCENT_ORANGE  = "#ff9f0a"   # Apple orange (quick export)
TEXT_PRIMARY   = "#f2f2f7"
TEXT_SECONDARY = "#8e8e93"
TEXT_MUTED     = "#48484a"
BORDER         = "#2c2c2e"
FONT_FAMILY    = "Segoe UI"

APP_VERSION    = "1.3.0"
APP_TITLE      = "Apple Health → CSV Converter"


def _months_ago(n: int) -> datetime:
    """Return a timezone-aware datetime exactly n months before now."""
    now = datetime.now(tz=timezone.utc)
    # Roll back month by month
    month = now.month - n
    year = now.year + month // 12
    month = month % 12
    if month <= 0:
        month += 12
        year -= 1
    try:
        return now.replace(year=year, month=month)
    except ValueError:
        # Handle edge-cases like Feb 30 → last day of month
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        return now.replace(year=year, month=month, day=last_day)


class AppleHealthConverter(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.configure(bg=BG_DARK)
        self.resizable(False, False)

        # Center window (slightly taller for the new button row)
        w, h = 680, 740
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
        self._output_folder_path: Path | None = None

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_ui(self):
        # Top accent bar
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

        # Logo + title row
        title_frame = tk.Frame(self, bg=BG_DARK)
        title_frame.pack(fill="x", padx=28, pady=(18, 0))

        tk.Label(
            title_frame, text="♥", font=(FONT_FAMILY, 28), bg=BG_DARK, fg=ACCENT
        ).pack(side="left", pady=(0, 4))

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

        # Divider
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=28, pady=14)

        # ── Folder Selection Card ──────────────────────────────────────────
        card = tk.Frame(self, bg=BG_CARD, bd=0, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill="x", padx=28)

        tk.Label(
            card,
            text="STEP 1 — SELECT YOUR EXPORT FOLDER",
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_CARD,
            fg=TEXT_MUTED,
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
        tk.Label(
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
        ).pack(side="left", fill="x", expand=True)

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
            padx=12, pady=8, bd=0,
            command=self._browse_folder,
        )
        self._browse_btn.pack(side="left", padx=(8, 0))

        # Validation status
        self._validation_var = tk.StringVar(value="")
        self._validation_label = tk.Label(
            self,
            textvariable=self._validation_var,
            font=(FONT_FAMILY, 9),
            bg=BG_DARK,
            fg=TEXT_SECONDARY,
        )
        self._validation_label.pack(anchor="w", padx=28, pady=(8, 0))

        # ── STEP 2: Action Buttons ─────────────────────────────────────────
        tk.Label(
            self,
            text="STEP 2 — CHOOSE EXPORT MODE",
            font=(FONT_FAMILY, 8, "bold"),
            bg=BG_DARK,
            fg=TEXT_MUTED,
        ).pack(anchor="w", padx=28, pady=(14, 6))

        btn_row = tk.Frame(self, bg=BG_DARK)
        btn_row.pack(fill="x", padx=28, pady=(0, 4))

        # Full export button
        self._convert_btn = tk.Button(
            btn_row,
            text="⚡  Full Export",
            font=(FONT_FAMILY, 11, "bold"),
            bg=ACCENT,
            fg="white",
            activebackground="#cc2d4a",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=0, pady=13, bd=0,
            state="disabled",
            command=lambda: self._start_conversion(mode="full"),
        )
        self._convert_btn.pack(side="left", fill="x", expand=True)

        btn_row_2 = tk.Frame(self, bg=BG_DARK)
        btn_row_2.pack(fill="x", padx=28, pady=(0, 4))

        # Last 1 Month button
        self._month1_btn = tk.Button(
            btn_row_2,
            text="📅  Last 1 Month",
            font=(FONT_FAMILY, 11, "bold"),
            bg=ACCENT_ORANGE,
            fg="white",
            activebackground="#cc7d08",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=0, pady=13, bd=0,
            state="disabled",
            command=lambda: self._start_conversion(mode="1mo"),
        )
        self._month1_btn.pack(side="left", fill="x", expand=True)

        # Spacer
        tk.Frame(btn_row_2, bg=BG_DARK, width=8).pack(side="left")

        # Last 2 Months button
        self._month2_btn = tk.Button(
            btn_row_2,
            text="📅  Last 2 Months",
            font=(FONT_FAMILY, 11, "bold"),
            bg=ACCENT_ORANGE,
            fg="white",
            activebackground="#cc7d08",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=0, pady=13, bd=0,
            state="disabled",
            command=lambda: self._start_conversion(mode="2mo"),
        )
        self._month2_btn.pack(side="left", fill="x", expand=True)

        btn_row_3 = tk.Frame(self, bg=BG_DARK)
        btn_row_3.pack(fill="x", padx=28, pady=(0, 4))

        # Last 3 Months button
        self._month3_btn = tk.Button(
            btn_row_3,
            text="📅  Last 3 Months",
            font=(FONT_FAMILY, 11, "bold"),
            bg=ACCENT_ORANGE,
            fg="white",
            activebackground="#cc7d08",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=0, pady=13, bd=0,
            state="disabled",
            command=lambda: self._start_conversion(mode="3mo"),
        )
        self._month3_btn.pack(side="left", fill="x", expand=True)

        # Spacer
        tk.Frame(btn_row_3, bg=BG_DARK, width=8).pack(side="left")

        # Last 6 Months button
        self._month6_btn = tk.Button(
            btn_row_3,
            text="📅  Last 6 Months",
            font=(FONT_FAMILY, 11, "bold"),
            bg=ACCENT_ORANGE,
            fg="white",
            activebackground="#cc7d08",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=0, pady=13, bd=0,
            state="disabled",
            command=lambda: self._start_conversion(mode="6mo"),
        )
        self._month6_btn.pack(side="left", fill="x", expand=True)

        # Select Topics Checkbox
        self._select_topics_var = tk.BooleanVar(value=False)
        self._select_topics_chk = tk.Checkbutton(
            self,
            text="Let me select specific topics before exporting",
            variable=self._select_topics_var,
            font=(FONT_FAMILY, 9),
            bg=BG_DARK,
            fg=TEXT_SECONDARY,
            selectcolor=BG_DARK,
            activebackground=BG_DARK,
            activeforeground=TEXT_SECONDARY,
        )
        self._select_topics_chk.pack(anchor="w", padx=28, pady=(8, 0))

        # Mode description label
        self._mode_desc_var = tk.StringVar(value="")
        tk.Label(
            self,
            textvariable=self._mode_desc_var,
            font=(FONT_FAMILY, 8),
            bg=BG_DARK,
            fg=TEXT_MUTED,
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(4, 0))

        # ── Progress Card ──────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=28, pady=(14, 0))

        prog_card = tk.Frame(self, bg=BG_CARD, bd=0, highlightthickness=1,
                             highlightbackground=BORDER)
        prog_card.pack(fill="x", padx=28, pady=0)

        prog_header = tk.Frame(prog_card, bg=BG_CARD)
        prog_header.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(
            prog_header,
            text="STEP 3 — PROGRESS",
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

        stats_row = tk.Frame(prog_card, bg=BG_CARD)
        stats_row.pack(fill="x", padx=16, pady=(0, 14))

        self._rec_var   = tk.StringVar(value="Records: —")
        self._types_var = tk.StringVar(value="Types: —")
        self._work_var  = tk.StringVar(value="Workouts: —")
        self._skip_var  = tk.StringVar(value="")

        for var in (self._rec_var, self._types_var, self._work_var, self._skip_var):
            tk.Label(
                stats_row,
                textvariable=var,
                font=(FONT_FAMILY, 9),
                bg=BG_CARD,
                fg=TEXT_MUTED,
            ).pack(side="left", padx=(0, 18))

        # ── Output area ────────────────────────────────────────────────────
        self._output_frame = tk.Frame(self, bg=BG_DARK)
        self._output_frame.pack(fill="x", padx=28, pady=10)

        self._output_var = tk.StringVar(value="")
        tk.Label(
            self._output_frame,
            textvariable=self._output_var,
            font=(FONT_FAMILY, 9),
            bg=BG_DARK,
            fg=ACCENT2,
            anchor="w",
            wraplength=620,
            justify="left",
        ).pack(anchor="w")

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
            padx=12, pady=7, bd=0,
            command=self._open_output,
        )

        # ── Footer ─────────────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=28, pady=(6, 0))
        tk.Label(
            self,
            text=f"v{APP_VERSION}  •  Processes data locally, nothing leaves your machine  •  Files auto-split at 10 MB",
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

        display = str(path)
        if len(display) > 60:
            display = "…" + display[-57:]
        self._folder_var.set(display)
        self._validate_folder(path)

    def _validate_folder(self, path: Path):
        xml_path = path / "export.xml"
        cda_path = path / "export_cda.xml"

        if not xml_path.exists():
            self._validation_var.set("⚠  export.xml not found — is this the right folder?")
            self._validation_label.configure(fg=ACCENT_ORANGE)
            self._set_buttons("disabled")
            return

        try:
            size_gb = xml_path.stat().st_size / (1024 ** 3)
            size_str = (
                f"{size_gb:.2f} GB" if size_gb >= 1
                else f"{xml_path.stat().st_size / (1024**2):.0f} MB"
            )
        except Exception:
            size_str = "unknown size"

        extras = []
        if cda_path.exists():
            extras.append("clinical records")
        gpx_count = len(list(path.glob("**/*.gpx")))
        if gpx_count:
            extras.append(f"{gpx_count} GPX routes")
        ecg_count = len(list(path.glob("**/*.csv")))
        if ecg_count:
            extras.append(f"{ecg_count} ECG files")

        extra_str = f"  +  {', '.join(extras)}" if extras else ""
        self._validation_var.set(f"✓  export.xml found ({size_str}){extra_str}")
        self._validation_label.configure(fg=ACCENT2)
        self._set_buttons("normal")
        self._status_var.set("Ready — choose an export mode above.")
        self._mode_desc_var.set(
            "Full Export: all data, one CSV per metric type  ·  "
            "Quick Export: everything in one combined CSV, Gemini-ready"
        )

    def _set_buttons(self, state: str):
        self._convert_btn.configure(state=state)
        self._month1_btn.configure(state=state)
        self._month2_btn.configure(state=state)
        self._month3_btn.configure(state=state)
        self._month6_btn.configure(state=state)

    def _start_conversion(self, mode: str):
        if self._running or not self._selected_folder:
            return

        self._running = True
        self._cancel_requested = False
        self._start_time = time.time()

        # Update UI
        self._browse_btn.configure(state="disabled")
        self._set_buttons("disabled")
        self._progress_bar.configure(mode="indeterminate")
        self._progress_bar.start(12)
        self._output_var.set("")
        self._skip_var.set("")
        try:
            self._open_btn.pack_forget()
        except Exception:
            pass

        labels = {
            "full": ("⚡  Full Export", "Converting full export…"),
            "1mo":  ("📅  Last 1 Month", "Extracting last 1 month…"),
            "2mo":  ("📅  Last 2 Months", "Extracting last 2 months…"),
            "3mo":  ("📅  Last 3 Months", "Extracting last 3 months…"),
            "6mo":  ("📅  Last 6 Months", "Extracting last 6 months…"),
        }
        lbl, converting_text = labels.get(mode, ("⚡  Full Export", "Converting…"))
        self._convert_btn.configure(text="Converting…" if mode == "full" else "⚡  Full Export")
        if mode == "1mo":
            self._month1_btn.configure(text="Extracting…")
        elif mode == "2mo":
            self._month2_btn.configure(text="Extracting…")
        elif mode == "3mo":
            self._month3_btn.configure(text="Extracting…")
        elif mode == "6mo":
            self._month6_btn.configure(text="Extracting…")

        if self._select_topics_var.get():
            t = threading.Thread(target=self._run_prescan, args=(mode,), daemon=True)
        else:
            t = threading.Thread(target=self._run_conversion, args=(mode, None), daemon=True)
        t.start()
        self._tick_elapsed()

    def _tick_elapsed(self):
        if self._running:
            elapsed = time.time() - self._start_time
            m, s = divmod(int(elapsed), 60)
            self._elapsed_var.set(f"Elapsed: {m:02d}:{s:02d}")
            self.after(1000, self._tick_elapsed)

    def _run_prescan(self, mode: str):
        try:
            from parser import prescan_topics
            
            folder = self._selected_folder
            if mode == "full":
                start_date = None
            else:
                if mode == "1mo": months = 1
                elif mode == "2mo": months = 2
                elif mode == "3mo": months = 3
                else: months = 6
                start_date = _months_ago(months)

            self.after(0, lambda: self._status_var.set(
                "Scanning file for available topics (this may take a few minutes)..."
            ))

            def on_progress(count, _):
                self.after(0, lambda: self._status_var.set(f"Scanning records: {count:,}..."))
                
            def cancel_check():
                return self._cancel_requested

            topics = prescan_topics(
                export_folder=folder,
                start_date=start_date,
                progress_callback=on_progress,
                cancel_check=cancel_check
            )
            
            if self._cancel_requested:
                self.after(0, lambda: self._on_error("Cancelled by user"))
                return

            if not topics:
                self.after(0, lambda: self._on_error("No topics found in the selected date range."))
                return

            self.after(0, lambda: self._show_topic_selection(topics, mode))
            
        except Exception as e:
            import traceback
            self.after(0, lambda: self._on_error(f"Prescan error: {e}"))

    def _show_topic_selection(self, topics: list, mode: str):
        # Stop the spinning progress bar while they select
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(100)
        self._status_var.set("Please select topics in the popup window...")

        top = tk.Toplevel(self)
        top.title("Select Topics to Export")
        top.configure(bg=BG_DARK)
        top.geometry("400x500")
        top.transient(self)
        top.grab_set()

        # Center top relative to main window
        top.geometry(f"+{self.winfo_x() + 140}+{self.winfo_y() + 90}")

        tk.Label(top, text="Select topics to include:", font=(FONT_FAMILY, 10, "bold"), bg=BG_DARK, fg=TEXT_PRIMARY).pack(pady=10)

        # Buttons
        btn_frame = tk.Frame(top, bg=BG_DARK)
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        def select_all():
            for var in var_dict.values(): var.set(True)
        def select_none():
            for var in var_dict.values(): var.set(False)

        tk.Button(btn_frame, text="Select All", command=select_all, bg=BG_CARD2, fg=TEXT_PRIMARY, relief="flat").pack(side="left", padx=5)
        tk.Button(btn_frame, text="Select None", command=select_none, bg=BG_CARD2, fg=TEXT_PRIMARY, relief="flat").pack(side="left", padx=5)

        # Canvas with scrollbar
        frame_canvas = tk.Frame(top, bg=BG_DARK)
        frame_canvas.pack(fill="both", expand=True, padx=10, pady=5)
        
        canvas = tk.Canvas(frame_canvas, bg=BG_CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame_canvas, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG_CARD)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        var_dict = {}
        for t in topics:
            var = tk.BooleanVar(value=True)
            var_dict[t] = var
            clean_name = t.replace("HKQuantityTypeIdentifier", "").replace("HKCategoryTypeIdentifier", "")
            chk = tk.Checkbutton(
                scrollable_frame, text=clean_name, variable=var,
                bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_CARD,
                activebackground=BG_CARD, activeforeground=TEXT_PRIMARY
            )
            chk.pack(anchor="w", padx=5, pady=2)

        def confirm():
            selected = {t for t, v in var_dict.items() if v.get()}
            top.destroy()
            if not selected:
                self._on_error("No topics selected.")
                return
            
            # Restart progress bar and continue
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
            self._status_var.set("Starting conversion...")
            
            # Re-fetch mode text for buttons
            mode_lbl = "Converting..." if mode == "full" else "Extracting..."
            if mode == "full": self._convert_btn.configure(text=mode_lbl)
            elif mode == "1mo": self._month1_btn.configure(text=mode_lbl)
            elif mode == "2mo": self._month2_btn.configure(text=mode_lbl)
            elif mode == "3mo": self._month3_btn.configure(text=mode_lbl)
            elif mode == "6mo": self._month6_btn.configure(text=mode_lbl)

            t_conv = threading.Thread(target=self._run_conversion, args=(mode, selected), daemon=True)
            t_conv.start()

        def cancel():
            top.destroy()
            self._on_error("Topic selection cancelled.")

        btn_confirm = tk.Frame(top, bg=BG_DARK)
        btn_confirm.pack(fill="x", pady=10)
        tk.Button(btn_confirm, text="Continue Export", font=(FONT_FAMILY, 10, "bold"), bg=ACCENT2, fg="white", command=confirm, relief="flat", padx=10, pady=5).pack(side="right", padx=10)
        tk.Button(btn_confirm, text="Cancel", bg=BG_CARD2, fg=TEXT_PRIMARY, command=cancel, relief="flat", padx=10, pady=5).pack(side="right", padx=10)

        top.protocol("WM_DELETE_WINDOW", cancel)

    def _run_conversion(self, mode: str, allowed_topics: set = None):
        try:
            from writers import OutputManager, QuickExportManager
            from parser import parse_export

            folder = self._selected_folder

            if mode == "full":
                output_mgr = OutputManager(folder)
                start_date = None
                self.after(0, lambda: self._status_var.set(
                    "Parsing export.xml — this may take several minutes for large exports…"
                ))
            else:
                if mode == "1mo": months = 1
                elif mode == "2mo": months = 2
                elif mode == "3mo": months = 3
                else: months = 6
                output_mgr = QuickExportManager(folder, months)
                start_date = _months_ago(months)
                self.after(0, lambda: self._status_var.set(
                    f"Filtering records since {start_date.strftime('%b %d, %Y')} — scanning export.xml…"
                ))

            def on_progress(total, current_type):
                short = (current_type
                         .replace("HKQuantityTypeIdentifier", "")
                         .replace("HKCategoryTypeIdentifier", ""))
                self.after(0, lambda: self._update_progress(total, short, output_mgr))

            def cancel_check():
                return self._cancel_requested

            stats = parse_export(
                export_folder=folder,
                output_manager=output_mgr,
                progress_callback=on_progress,
                cancel_check=cancel_check,
                start_date=start_date,
                allowed_topics=allowed_topics,
            )

            self.after(0, lambda: self._status_var.set("Finalizing CSV files…"))
            out_path = output_mgr.close_and_write_summary()

            self.after(0, lambda: self._on_success(stats, out_path, mode, output_mgr))

        except Exception as e:
            import traceback
            self.after(0, lambda: self._on_error(str(e)))

    def _update_progress(self, total: int, current_type: str, mgr):
        self._status_var.set(f"Processing: {current_type}…")
        self._rec_var.set(f"Records: {total:,}")
        self._types_var.set(f"Types: {mgr.type_count()}")
        if hasattr(mgr, "workout_count"):
            self._work_var.set(f"Workouts: {mgr.workout_count:,}")

    def _on_success(self, stats: dict, out_path: Path, mode: str, mgr):
        self._running = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(100)

        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)

        total    = stats["total_records"]
        workouts = stats["workouts"]
        activity = stats["activity_summaries"]
        skipped  = stats.get("skipped", 0)
        errors   = stats.get("errors", 0)

        self._rec_var.set(f"Records: {total:,}")
        self._work_var.set(f"Workouts: {workouts:,}")
        if skipped:
            self._skip_var.set(f"Filtered out: {skipped:,}")

        self._status_label.configure(fg=ACCENT2)

        if mode == "full":
            types = stats["record_types"]
            self._types_var.set(f"Types: {types}")
            self._status_var.set(
                f"✓ Complete in {m}m {s}s  —  {total:,} records  ·  {types} metric types  ·  "
                f"{workouts:,} workouts  ·  {activity:,} activity days"
                + (f"  ·  {errors} warnings" if errors else "")
            )
            out_dir = out_path.parent
            self._output_var.set(f"Output folder: {out_dir}\nOne CSV per metric type + summary.")
        else:
            if mode == "1mo": months = 1
            elif mode == "2mo": months = 2
            elif mode == "3mo": months = 3
            else: months = 6
            parts = getattr(mgr, "part_count", 1)
            files_str = (
                f"{parts} files (auto-split at 10 MB)" if parts > 1
                else "1 combined CSV file"
            )
            self._status_var.set(
                f"✓ Complete in {m}m {s}s  —  {total:,} records from the last {months} month(s)  ·  "
                f"{workouts:,} workouts  ·  {skipped:,} older records skipped"
                + (f"  ·  {errors} warnings" if errors else "")
            )
            out_dir = out_path.parent
            self._output_var.set(
                f"Output folder: {out_dir}\n"
                f"{files_str}  →  {out_path.name}"
            )

        self._output_folder_path = out_path.parent
        self._open_btn.pack(anchor="w", pady=(6, 0))

        # Reset buttons
        self._browse_btn.configure(state="normal")
        self._convert_btn.configure(state="normal", text="⚡  Full Export")
        self._month1_btn.configure(state="normal", text="📅  Last 1 Month")
        self._month2_btn.configure(state="normal", text="📅  Last 2 Months")
        self._month3_btn.configure(state="normal", text="📅  Last 3 Months")
        self._month6_btn.configure(state="normal", text="📅  Last 6 Months")

    def _on_error(self, message: str):
        self._running = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(0)

        self._status_label.configure(fg=ACCENT)
        self._status_var.set(f"✗ Error: {message}")

        self._browse_btn.configure(state="normal")
        self._convert_btn.configure(state="normal", text="⚡  Full Export")
        self._month1_btn.configure(state="normal", text="📅  Last 1 Month")
        self._month2_btn.configure(state="normal", text="📅  Last 2 Months")
        self._month3_btn.configure(state="normal", text="📅  Last 3 Months")
        self._month6_btn.configure(state="normal", text="📅  Last 6 Months")

        messagebox.showerror(
            "Conversion Error",
            f"An error occurred during conversion:\n\n{message}\n\n"
            "Please check that the export folder is valid and not corrupted.",
        )

    def _open_output(self):
        if self._output_folder_path and self._output_folder_path.exists():
            os.startfile(str(self._output_folder_path))


if __name__ == "__main__":
    app = AppleHealthConverter()
    app.mainloop()
