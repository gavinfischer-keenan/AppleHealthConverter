"""
writers.py — CSV writer manager for Apple Health Converter.

Creates one CSV file per record type discovered in the export.
Handles dynamic column discovery (some records have optional fields).
"""

import csv
import os
from pathlib import Path
from typing import Dict, Optional, List


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

# Columns for metadata CSV
METADATA_COLUMNS = [
    "field",
    "value",
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


def _safe_filename(record_type: str) -> str:
    """Convert an HK type identifier to a safe filename."""
    # Strip the HK prefix namespacing for readability
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
    # Sanitize any remaining unsafe chars
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe[:120]  # keep filenames reasonable


class RecordTypeWriter:
    """Manages a single CSV file for one health record type."""

    def __init__(self, output_dir: Path, record_type: str):
        self.record_type = record_type
        self.short_name = _safe_filename(record_type)
        self.filename = f"{self.short_name}.csv"
        self.filepath = output_dir / self.filename

        self._file = open(self.filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=RECORD_COLUMNS,
            extrasaction="ignore",
            restval="",
        )
        self._writer.writeheader()

        # Stats tracking
        self.count = 0
        self.earliest: Optional[str] = None
        self.latest: Optional[str] = None
        self.unit: str = ""
        self.sources: set = set()

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

    def close(self):
        self._file.close()

    def summary_row(self) -> dict:
        return {
            "record_type": self.record_type,
            "short_name": self.short_name,
            "count": self.count,
            "earliest_date": self.earliest or "",
            "latest_date": self.latest or "",
            "unit": self.unit,
            "sources": " | ".join(sorted(self.sources)),
            "filename": self.filename,
        }


class OutputManager:
    """
    Manages all output CSV writers.
    Creates the output directory and lazily opens one CSV per record type.
    """

    def __init__(self, export_folder: Path):
        self.output_dir = export_folder / "converted"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Per-type writers
        self._type_writers: Dict[str, RecordTypeWriter] = {}

        # Special fixed-schema writers
        self._workout_file = open(
            self.output_dir / "_workouts.csv", "w", newline="", encoding="utf-8"
        )
        self._workout_writer = csv.DictWriter(
            self._workout_file,
            fieldnames=WORKOUT_COLUMNS,
            extrasaction="ignore",
            restval="",
        )
        self._workout_writer.writeheader()

        self._workout_stats_file = open(
            self.output_dir / "_workout_stats.csv", "w", newline="", encoding="utf-8"
        )
        self._workout_stats_writer = csv.DictWriter(
            self._workout_stats_file,
            fieldnames=WORKOUT_STATS_COLUMNS,
            extrasaction="ignore",
            restval="",
        )
        self._workout_stats_writer.writeheader()

        self._activity_file = open(
            self.output_dir / "_activity_summaries.csv", "w", newline="", encoding="utf-8"
        )
        self._activity_writer = csv.DictWriter(
            self._activity_file,
            fieldnames=ACTIVITY_SUMMARY_COLUMNS,
            extrasaction="ignore",
            restval="",
        )
        self._activity_writer.writeheader()

        # Counters
        self.workout_count = 0
        self.workout_stats_count = 0
        self.activity_count = 0

    def write_record(self, row: dict):
        rtype = row.get("type", "Unknown")
        if rtype not in self._type_writers:
            self._type_writers[rtype] = RecordTypeWriter(self.output_dir, rtype)
        self._type_writers[rtype].write(row)

    def write_workout(self, row: dict):
        self._workout_writer.writerow(row)
        self.workout_count += 1

    def write_workout_stats(self, row: dict):
        self._workout_stats_writer.writerow(row)
        self.workout_stats_count += 1

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

    def close_and_write_summary(self):
        """Close all writers and produce the summary CSV."""
        # Close per-type writers
        for tw in self._type_writers.values():
            tw.close()

        # Close special writers
        self._workout_file.close()
        self._workout_stats_file.close()
        self._activity_file.close()

        # Write summary
        summary_path = self.output_dir / "_summary.csv"
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore", restval="")
            w.writeheader()
            # Write per-type summaries sorted by count desc
            rows = [tw.summary_row() for tw in self._type_writers.values()]
            rows.sort(key=lambda r: r["count"], reverse=True)
            w.writerows(rows)

            # Add special file entries
            if self.workout_count:
                w.writerow({
                    "record_type": "HKWorkout",
                    "short_name": "Workouts",
                    "count": self.workout_count,
                    "earliest_date": "",
                    "latest_date": "",
                    "unit": "",
                    "sources": "",
                    "filename": "_workouts.csv",
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
                    "filename": "_workout_stats.csv",
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
