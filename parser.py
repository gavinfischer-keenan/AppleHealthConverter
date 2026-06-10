"""
parser.py — Streaming XML engine for Apple Health Converter.

Uses iterparse to handle multi-GB export.xml files without loading
the entire document into memory. Calls back into OutputManager for
each parsed element.

v1.1: Added optional start_date filter for quick monthly exports.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


# Progress callback type: (records_processed: int, current_type: str) -> None
ProgressCallback = Callable[[int, str], None]

# Strip control characters that Apple Health sometimes embeds
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Date formats Apple Health uses in its XML attributes
_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def _parse_date(date_str: str) -> Optional[datetime]:
    """Attempt to parse an Apple Health date string into a datetime object."""
    if not date_str:
        return None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _clean_stream(filepath: Path):
    """
    Generator that yields cleaned lines from a potentially dirty XML file.
    Removes invalid XML control characters and strips the DOCTYPE declaration
    that Apple includes (which can confuse parsers looking for DTDs).
    """
    with open(filepath, "rb") as f:
        for raw_line in f:
            try:
                line = raw_line.decode("utf-8", errors="replace")
            except Exception:
                line = raw_line.decode("latin-1", errors="replace")

            # Strip DOCTYPE — Apple's DTD reference may not be reachable
            if "<!DOCTYPE" in line:
                line = re.sub(r"<!DOCTYPE[^>]*>", "", line)

            # Strip invalid XML control characters
            line = _CONTROL_CHAR_RE.sub("", line)

            yield line.encode("utf-8")


def _flatten_metadata(elem) -> dict:
    """Extract MetadataEntry children into a flat dict with metadata_ prefix."""
    meta = {}
    for child in elem:
        if child.tag == "MetadataEntry":
            key = child.attrib.get("key", "").replace(" ", "_").replace("/", "_")
            val = child.attrib.get("value", "")
            meta[f"metadata_{key}"] = val
    return meta


def parse_export(
    export_folder: Path,
    output_manager,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    start_date: Optional[datetime] = None,
) -> dict:
    """
    Stream-parse the export.xml file and write output via output_manager.

    Args:
        export_folder:    Path to the apple_health_export folder.
        output_manager:   OutputManager or QuickExportManager instance.
        progress_callback: Called every 5,000 records with (count, type_string).
        cancel_check:     Called periodically; return True to abort.
        start_date:       If set, only records with startDate >= this value are
                          written. Records before this date are silently skipped.
                          Pass a timezone-aware datetime.

    Returns:
        dict with final stats: total_records, record_types, workouts,
        activity_summaries, skipped, errors.
    """
    xml_path = export_folder / "export.xml"
    if not xml_path.exists():
        raise FileNotFoundError(f"export.xml not found in {export_folder}")

    stats = {
        "total_records": 0,
        "record_types": 0,
        "workouts": 0,
        "workout_stats": 0,
        "activity_summaries": 0,
        "skipped": 0,
        "errors": 0,
        "export_date": "",
        "source_device": "",
    }

    metadata_pairs = []
    current_workout: Optional[dict] = None
    current_workout_in_range: bool = True  # track if workout passes date filter

    record_count = 0
    PROGRESS_INTERVAL = 5000

    def _in_range(date_str: str) -> bool:
        """Return True if this record should be included."""
        if start_date is None:
            return True
        dt = _parse_date(date_str)
        if dt is None:
            return True  # include records with unparseable dates (safe default)
        return dt >= start_date

    try:
        source = _clean_stream(xml_path)

        class LineIterSource:
            """Wraps a line generator as a file-like object for iterparse."""
            def __init__(self, gen):
                self._gen = gen
                self._buf = b""

            def read(self, size=-1):
                if size == -1:
                    return b"".join(self._gen)
                while len(self._buf) < size:
                    try:
                        self._buf += next(self._gen)
                    except StopIteration:
                        break
                chunk, self._buf = self._buf[:size], self._buf[size:]
                return chunk

        context = ET.iterparse(LineIterSource(source), events=("start", "end"))

        for event, elem in context:
            if cancel_check and cancel_check():
                break

            try:
                if event == "start":
                    if elem.tag == "Workout":
                        current_workout = dict(elem.attrib)
                        # Pre-check if this workout is in date range
                        current_workout_in_range = _in_range(
                            elem.attrib.get("startDate", "")
                        )

                elif event == "end":
                    tag = elem.tag

                    if tag == "HealthData":
                        metadata_pairs.append(("locale", elem.attrib.get("locale", "")))

                    elif tag == "Me":
                        for k, v in elem.attrib.items():
                            metadata_pairs.append((k, v))

                    elif tag == "Record":
                        row = dict(elem.attrib)
                        # ── Date filter ──
                        if not _in_range(row.get("startDate", "")):
                            stats["skipped"] += 1
                        else:
                            output_manager.write_record(row)
                            stats["total_records"] += 1
                            record_count += 1

                            if record_count % PROGRESS_INTERVAL == 0:
                                rtype = row.get("type", "")
                                if progress_callback:
                                    progress_callback(
                                        stats["total_records"] + stats["workouts"] + stats["activity_summaries"],
                                        rtype,
                                    )

                    elif tag == "Workout":
                        if current_workout_in_range:
                            row = dict(elem.attrib)
                            row.update(_flatten_metadata(elem))
                            output_manager.write_workout(row)
                            stats["workouts"] += 1
                        else:
                            stats["skipped"] += 1
                        current_workout = None
                        current_workout_in_range = True

                    elif tag == "WorkoutStatistics":
                        if current_workout_in_range:
                            row = dict(elem.attrib)
                            if current_workout:
                                row["workout_startDate"] = current_workout.get("startDate", "")
                                row["workout_endDate"] = current_workout.get("endDate", "")
                                row["workout_activityType"] = current_workout.get("workoutActivityType", "")
                            output_manager.write_workout_stats(row)
                            stats["workout_stats"] += 1

                    elif tag == "ActivitySummary":
                        row = dict(elem.attrib)
                        # ActivitySummary uses dateComponents (YYYY-MM-DD)
                        if _in_range(row.get("dateComponents", "")):
                            output_manager.write_activity_summary(row)
                            stats["activity_summaries"] += 1
                        else:
                            stats["skipped"] += 1

                    elif tag == "ExportDate":
                        val = elem.attrib.get("value", "")
                        stats["export_date"] = val
                        metadata_pairs.append(("export_date", val))

                    elem.clear()

            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 10:
                    print(f"[WARNING] Error processing element <{elem.tag}>: {e}")

    except ET.ParseError as e:
        raise RuntimeError(
            f"XML parse error in export.xml: {e}\n"
            "The file may be corrupted or use an unsupported encoding."
        )

    output_manager.write_metadata(metadata_pairs)
    stats["record_types"] = output_manager.type_count()
    return stats
