"""
writers.py — CSV writer manager for Apple Health Converter.

Creates one CSV file per record type discovered in the export.
Files are automatically split into parts when they reach 10 MB.
Also includes QuickExportManager for single-file monthly exports.
"""

import csv
import os
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


# ── File size split threshold ────────────────────────────────────────────────
SPLIT_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB

# Canonical column order for the main Record CSV files
RECORD_COLUMNS = [
    "type",
    "sourceName",
    "sourceVersion",
    "device",
    "unit",
    "creationDate",
    "startDate",
    "endDate",
    "value",
]

# Columns for Workout CSV
WORKOUT_COLUMNS = [
    "workoutActivityType",
    "duration",
    "durationUnit",
    "totalDistance",
    "totalDistanceUnit",
    "totalEnergyBurned",
    "totalEnergyBurnedUnit",
    "sourceName",
    "sourceVersion",
    "device",
    "creationDate",
    "startDate",
    "endDate",
    "metadata_indoorWorkout",
    "metadata_averageMETs",
    "metadata_timeZone",
    "metadata_weatherTemperature",
    "metadata_weatherHumidity",
]

# Columns for WorkoutStatistics CSV
WORKOUT_STATS_COLUMNS = [
    "workout_startDate",
    "workout_endDate",
    "workout_activityType",
    "type",
    "unit",
    "sum",
    "minimum",
    "maximum",
    "average",
    "startDate",
    "endDate",
]

# Columns for ActivitySummary CSV
ACTIVITY_SUMMARY_COLUMNS = [
    "dateComponents",
    "activeEnergyBurned",
    "activeEnergyBurnedGoal",
    "activeEnergyBurnedUnit",
    "appleMoveTime",
    "appleMoveTimeGoal",
    "appleExerciseTime",
    "appleExerciseTimeGoal",
    "appleStandHours",
    "appleStandHoursGoal",
]

# Columns for summary CSV
SUMMARY_COLUMNS = [
    "record_type",
    "short_name",
    "count",
    "earliest_date",
    "latest_date",
    "unit",
    "sources",
    "filename",
]

# Combined columns for single-file quick export (type is first)
COMBINED_COLUMNS = RECORD_COLUMNS  # already has 'type' as first column


def _safe_filename(record_type: str) -> str:
    """Convert an HK type identifier to a safe, readable filename."""
    name = record_type
    for prefix in [
        "HKQuantityTypeIdentifier",
        "HKCategoryTypeIdentifier",
        "HKDataType",
        "HKCorrelationTypeIdentifier",
        "HKWorkoutType",
    ]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe[:120]


def _open_csv(filepath: Path, fieldnames: list) -> tuple:
    """Open a CSV file and return (file_handle, DictWriter)."""
    f = open(filepath, "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
    w.writeheader()
    return f, w


class RecordTypeWriter:
    """
    Manages one or more CSV files for a single health record type.
    Automatically rolls to a new part file when the current file hits 10 MB.
    """

    def __init__(self, output_dir: Path, record_type: str):
        self.record_type = record_type
        self.short_name = _safe_filename(record_type)
        self.output_dir = output_dir

        self._part = 1
        self._filenames: List[str] = []
        self._open_part()

        # Stats
        self.count = 0
        self.earliest: Optional[str] = None
        self.latest: Optional[str] = None
        self.unit: str = ""
        self.sources: set = set()

    def _part_filename(self, part: int) -> str:
        if part == 1:
            return f"{self.short_name}.csv"
        return f"{self.short_name}_part{part}.csv"

    def _open_part(self):
        fname = self._part_filename(self._part)
        self._filenames.append(fname)
        fpath = self.output_dir / fname
        self._file, self._writer = _open_csv(fpath, RECORD_COLUMNS)
        self._current_path = fpath

    def _maybe_split(self):
        """Check file size and roll to next part if at or over threshold."""
        try:
            if self._current_path.stat().st_size >= SPLIT_THRESHOLD_BYTES:
                self._file.close()
                self._part += 1
                self._open_part()
        except OSError:
            pass  # Non-fatal; keep writing to current file

    def write(self, row: dict):
        self._writer.writerow(row)
        self.count += 1

        # Update stats
        sd = row.get("startDate", "")
        if sd:
            if self.earliest is None or sd < self.earliest:
                self.earliest = sd
            if self.latest is None or sd > self.latest:
                self.latest = sd

        if not self.unit and row.get("unit"):
            self.unit = row["unit"]

        src = row.get("sourceName", "")
        if src:
            self.sources.add(src)

        # Check split every 500 rows to keep overhead low
        if self.count % 500 == 0:
            self._maybe_split()

    def close(self):
        self._file.close()

    @property
    def filename(self) -> str:
        """Primary filename (part 1)."""
        return self._filenames[0] if self._filenames else f"{self.short_name}.csv"

    def summary_row(self) -> dict:
        parts_note = f" ({self._part} parts)" if self._part > 1 else ""
        return {
            "record_type": self.record_type,
            "short_name": self.short_name,
            "count": self.count,
            "earliest_date": self.earliest or "",
            "latest_date": self.latest or "",
            "unit": self.unit,
            "sources": " | ".join(sorted(self.sources)),
            "filename": self.filename + parts_note,
        }


class OutputManager:
    """
    Full-export output manager.
    Creates the output directory and lazily opens one CSV per record type.
    All files are auto-split at 10 MB.
    """

    def __init__(self, export_folder: Path):
        self.output_dir = export_folder / "converted"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._type_writers: Dict[str, RecordTypeWriter] = {}

        # Special fixed-schema writers (also split-aware)
        self._workout_path = self.output_dir / "_workouts.csv"
        self._workout_file, self._workout_writer = _open_csv(self._workout_path, WORKOUT_COLUMNS)
        self._workout_part = 1

        self._workout_stats_path = self.output_dir / "_workout_stats.csv"
        self._workout_stats_file, self._workout_stats_writer = _open_csv(
            self._workout_stats_path, WORKOUT_STATS_COLUMNS
        )
        self._workout_stats_part = 1

        self._activity_path = self.output_dir / "_activity_summaries.csv"
        self._activity_file, self._activity_writer = _open_csv(
            self._activity_path, ACTIVITY_SUMMARY_COLUMNS
        )

        self.workout_count = 0
        self.workout_stats_count = 0
        self.activity_count = 0

    def _split_fixed(self, current_path: Path, file_handle, writer_ref: str,
                     fieldnames: list, part_attr: str, count: int):
        """Roll a fixed-schema file to a new part if over threshold."""
        try:
            if current_path.stat().st_size >= SPLIT_THRESHOLD_BYTES:
                file_handle.close()
                part = getattr(self, part_attr) + 1
                setattr(self, part_attr, part)
                stem = current_path.stem.split("_part")[0]
                new_path = current_path.parent / f"{stem}_part{part}.csv"
                f, w = _open_csv(new_path, fieldnames)
                return new_path, f, w
        except OSError:
            pass
        return current_path, file_handle, getattr(self, writer_ref)

    def write_record(self, row: dict):
        rtype = row.get("type", "Unknown")
        if rtype not in self._type_writers:
            self._type_writers[rtype] = RecordTypeWriter(self.output_dir, rtype)
        self._type_writers[rtype].write(row)

    def write_workout(self, row: dict):
        self._workout_writer.writerow(row)
        self.workout_count += 1
        if self.workout_count % 500 == 0:
            try:
                if self._workout_path.stat().st_size >= SPLIT_THRESHOLD_BYTES:
                    self._workout_file.close()
                    self._workout_part += 1
                    self._workout_path = self.output_dir / f"_workouts_part{self._workout_part}.csv"
                    self._workout_file, self._workout_writer = _open_csv(
                        self._workout_path, WORKOUT_COLUMNS
                    )
            except OSError:
                pass

    def write_workout_stats(self, row: dict):
        self._workout_stats_writer.writerow(row)
        self.workout_stats_count += 1
        if self.workout_stats_count % 500 == 0:
            try:
                if self._workout_stats_path.stat().st_size >= SPLIT_THRESHOLD_BYTES:
                    self._workout_stats_file.close()
                    self._workout_stats_part += 1
                    self._workout_stats_path = self.output_dir / f"_workout_stats_part{self._workout_stats_part}.csv"
                    self._workout_stats_file, self._workout_stats_writer = _open_csv(
                        self._workout_stats_path, WORKOUT_STATS_COLUMNS
                    )
            except OSError:
                pass

    def write_activity_summary(self, row: dict):
        self._activity_writer.writerow(row)
        self.activity_count += 1

    def write_metadata(self, pairs: List[tuple]):
        meta_path = self.output_dir / "_metadata.csv"
        with open(meta_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["field", "value"])
            for k, v in pairs:
                w.writerow([k, v])

    def total_records(self) -> int:
        return sum(tw.count for tw in self._type_writers.values())

    def type_count(self) -> int:
        return len(self._type_writers)

    def close_and_write_summary(self) -> Path:
        """Close all writers and produce the summary CSV."""
        for tw in self._type_writers.values():
            tw.close()
        self._workout_file.close()
        self._workout_stats_file.close()
        self._activity_file.close()

        summary_path = self.output_dir / "_summary.csv"
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore", restval="")
            w.writeheader()
            rows = [tw.summary_row() for tw in self._type_writers.values()]
            rows.sort(key=lambda r: r["count"], reverse=True)
            w.writerows(rows)

            if self.workout_count:
                w.writerow({
                    "record_type": "HKWorkout",
                    "short_name": "Workouts",
                    "count": self.workout_count,
                    "earliest_date": "",
                    "latest_date": "",
                    "unit": "",
                    "sources": "",
                    "filename": f"_workouts.csv" + (f" ({self._workout_part} parts)" if self._workout_part > 1 else ""),
                })
            if self.workout_stats_count:
                w.writerow({
                    "record_type": "HKWorkoutStatistics",
                    "short_name": "WorkoutStatistics",
                    "count": self.workout_stats_count,
                    "earliest_date": "",
                    "latest_date": "",
                    "unit": "",
                    "sources": "",
                    "filename": f"_workout_stats.csv" + (f" ({self._workout_stats_part} parts)" if self._workout_stats_part > 1 else ""),
                })
            if self.activity_count:
                w.writerow({
                    "record_type": "HKActivitySummary",
                    "short_name": "ActivitySummaries",
                    "count": self.activity_count,
                    "earliest_date": "",
                    "latest_date": "",
                    "unit": "",
                    "sources": "",
                    "filename": "_activity_summaries.csv",
                })

        return summary_path


class QuickExportManager:
    """
    Single-file output manager for monthly quick exports.

    All health records (and workouts, activity summaries) go into one
    combined CSV. Files are split at 10 MB with _part2, _part3 suffixes.

    Output filename: quick_export_last_{months}mo_YYYYMMDD.csv
    """

    def __init__(self, export_folder: Path, months: int):
        self.output_dir = export_folder / "converted"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.months = months

        today_str = date.today().strftime("%Y%m%d")
        self._base_stem = f"quick_export_last_{months}mo_{today_str}"
        self._part = 1
        self._filenames: List[str] = []
        self._open_part()

        self.total_count = 0
        self.workout_count = 0
        self.activity_count = 0

    def _part_filename(self, part: int) -> str:
        if part == 1:
            return f"{self._base_stem}.csv"
        return f"{self._base_stem}_part{part}.csv"

    def _open_part(self):
        fname = self._part_filename(self._part)
        self._filenames.append(fname)
        fpath = self.output_dir / fname
        self._file, self._writer = _open_csv(fpath, COMBINED_COLUMNS)
        self._current_path = fpath

    def _maybe_split(self):
        try:
            if self._current_path.stat().st_size >= SPLIT_THRESHOLD_BYTES:
                self._file.close()
                self._part += 1
                self._open_part()
        except OSError:
            pass

    def write_record(self, row: dict):
        self._writer.writerow(row)
        self.total_count += 1
        if self.total_count % 500 == 0:
            self._maybe_split()

    def write_workout(self, row: dict):
        # Map workout fields onto the common record schema
        mapped = {
            "type": "HKWorkout",
            "sourceName": row.get("sourceName", ""),
            "sourceVersion": row.get("sourceVersion", ""),
            "device": row.get("device", ""),
            "unit": row.get("durationUnit", ""),
            "creationDate": row.get("creationDate", ""),
            "startDate": row.get("startDate", ""),
            "endDate": row.get("endDate", ""),
            "value": row.get("workoutActivityType", ""),
        }
        self._writer.writerow(mapped)
        self.total_count += 1
        self.workout_count += 1
        if self.total_count % 500 == 0:
            self._maybe_split()

    def write_workout_stats(self, row: dict):
        pass  # Omit sub-stats from quick export to keep it clean

    def write_activity_summary(self, row: dict):
        mapped = {
            "type": "HKActivitySummary",
            "sourceName": "",
            "sourceVersion": "",
            "device": "",
            "unit": "kcal / min / hrs",
            "creationDate": "",
            "startDate": row.get("dateComponents", ""),
            "endDate": row.get("dateComponents", ""),
            "value": (
                f"energy={row.get('activeEnergyBurned','')}/{row.get('activeEnergyBurnedGoal','')} "
                f"exercise={row.get('appleExerciseTime','')}/{row.get('appleExerciseTimeGoal','')} "
                f"stand={row.get('appleStandHours','')}/{row.get('appleStandHoursGoal','')}"
            ),
        }
        self._writer.writerow(mapped)
        self.total_count += 1
        self.activity_count += 1
        if self.total_count % 500 == 0:
            self._maybe_split()

    def write_metadata(self, pairs: List[tuple]):
        pass  # Not included in quick export

    def type_count(self) -> int:
        return 1  # Everything is in one file

    def close_and_write_summary(self) -> Path:
        """Close the file(s) and return the path to the first output file."""
        self._file.close()
        return self.output_dir / self._filenames[0]

    @property
    def part_count(self) -> int:
        return self._part

    @property
    def output_filenames(self) -> List[str]:
        return list(self._filenames)
