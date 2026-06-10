"""
parser.py — Streaming XML engine for Apple Health Converter.

Uses iterparse to handle multi-GB export.xml files without loading
the entire document into memory. Calls back into OutputManager for
each parsed element.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Optional
from writers import OutputManager


# Progress callback type: (records_processed: int, current_type: str) -> None
ProgressCallback = Callable[[int, str], None]

# Strip control characters that Apple Health sometimes embeds
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
                # Remove the DOCTYPE declaration entirely
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
    output_manager: OutputManager,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """
    Stream-parse the export.xml file and write output via output_manager.

    Args:
        export_folder: Path to the apple_health_export folder.
        output_manager: OutputManager instance to write CSVs.
        progress_callback: Called every 10,000 records with (count, type_string).
        cancel_check: Called periodically; return True to abort.

    Returns:
        dict with final stats: total_records, record_types, workouts,
        activity_summaries, errors.
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
        "errors": 0,
        "export_date": "",
        "source_device": "",
    }

    # We'll accumulate metadata from the <Me> element
    metadata_pairs = []

    # Current workout context (for associating WorkoutStatistics)
    current_workout: Optional[dict] = None

    record_count = 0
    PROGRESS_INTERVAL = 5000

    try:
        source = _clean_stream(xml_path)
        # iterparse needs a file-like object
        import io

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
            # Check for cancellation
            if cancel_check and cancel_check():
                break

            try:
                if event == "start":
                    # Capture workout context for child stats
                    if elem.tag == "Workout":
                        current_workout = dict(elem.attrib)

                elif event == "end":
                    tag = elem.tag

                    # ── HealthData root element: grab export metadata ──
                    if tag == "HealthData":
                        metadata_pairs.append(("locale", elem.attrib.get("locale", "")))

                    # ── Me element: personal info ──
                    elif tag == "Me":
                        for k, v in elem.attrib.items():
                            metadata_pairs.append((k, v))

                    # ── Regular health records ──
                    elif tag == "Record":
                        row = dict(elem.attrib)
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

                    # ── Workout sessions ──
                    elif tag == "Workout":
                        row = dict(elem.attrib)
                        # Flatten metadata children
                        row.update(_flatten_metadata(elem))
                        output_manager.write_workout(row)
                        stats["workouts"] += 1
                        current_workout = None  # reset after Workout end

                    # ── Workout statistics (nested in Workout) ──
                    elif tag == "WorkoutStatistics":
                        row = dict(elem.attrib)
                        if current_workout:
                            row["workout_startDate"] = current_workout.get("startDate", "")
                            row["workout_endDate"] = current_workout.get("endDate", "")
                            row["workout_activityType"] = current_workout.get("workoutActivityType", "")
                        output_manager.write_workout_stats(row)
                        stats["workout_stats"] += 1

                    # ── Daily activity summaries (rings) ──
                    elif tag == "ActivitySummary":
                        row = dict(elem.attrib)
                        output_manager.write_activity_summary(row)
                        stats["activity_summaries"] += 1

                    # ── ExportDate ──
                    elif tag == "ExportDate":
                        val = elem.attrib.get("value", "")
                        stats["export_date"] = val
                        metadata_pairs.append(("export_date", val))

                    # Free memory immediately after processing
                    elem.clear()

            except Exception as e:
                stats["errors"] += 1
                # Log and continue — don't crash on a single bad record
                if stats["errors"] <= 10:  # limit noise
                    print(f"[WARNING] Error processing element <{elem.tag}>: {e}")

    except ET.ParseError as e:
        raise RuntimeError(
            f"XML parse error in export.xml: {e}\n"
            "The file may be corrupted or use an unsupported encoding."
        )

    # Write metadata CSV
    output_manager.write_metadata(metadata_pairs)

    stats["record_types"] = output_manager.type_count()
    return stats
