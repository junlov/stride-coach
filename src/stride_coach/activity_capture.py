"""Garmin detail normalization and resumable, paced per-run capture."""

import hashlib
import io
import os
import struct
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .activity_models import BackfillResult, HeartRateZone, RunLap, RunMetrics, RunStreams
from .activity_storage import mark_attempt, pending_ids, save_details, store_gps
from .garmin_auth import GarminError

# Units follow the activity-service summary contract, not the user's display units.
METRICS = {
    "moving_time_s": "movingDuration",
    "elapsed_time_s": "elapsedDuration",
    "average_speed_m_s": "averageSpeed",
    "max_speed_m_s": "maxSpeed",
    "max_hr": "maxHR",
    "average_cadence_spm": "averageRunningCadenceInStepsPerMinute",
    "max_cadence_spm": "maxRunningCadenceInStepsPerMinute",
    "stride_length_cm": "avgStrideLength",
    "vertical_oscillation_cm": "avgVerticalOscillation",
    "vertical_ratio_percent": "avgVerticalRatio",
    "ground_contact_time_ms": "avgGroundContactTime",
    "average_power_w": "avgPower",
    "max_power_w": "maxPower",
    "normalized_power_w": "normPower",
    "elevation_gain_m": "elevationGain",
    "elevation_loss_m": "elevationLoss",
    "min_elevation_m": "minElevation",
    "max_elevation_m": "maxElevation",
    "average_temperature_c": "averageTemperature",
    "min_temperature_c": "minTemperature",
    "max_temperature_c": "maxTemperature",
    "calories": "calories",
    "aerobic_training_effect": "trainingEffect",
    "anaerobic_training_effect": "anaerobicTrainingEffect",
    "training_load": "activityTrainingLoad",
    "vo2_max": "vO2MaxValue",
}


def normalize_metrics(payload: dict) -> RunMetrics:
    summary = {**payload, **payload.get("summaryDTO", {})}
    values = {name: summary[key] for name, key in METRICS.items() if summary.get(key) is not None}
    aliases = {
        "average_cadence_spm": "averageRunCadence",
        "max_cadence_spm": "maxRunCadence",
        "average_power_w": "averagePower",
        "normalized_power_w": "normalizedPower",
        "aerobic_training_effect": "aerobicTrainingEffect",
        "vo2_max": "vo2MaxValue",
    }
    for name, key in aliases.items():
        if name not in values and summary.get(key) is not None:
            values[name] = summary[key]
    for pace, speed in (
        ("average_pace_s_km", "average_speed_m_s"),
        ("max_pace_s_km", "max_speed_m_s"),
    ):
        if values.get(speed, 0) > 0:
            values[pace] = 1000 / values[speed]
    if summary.get("startTimeGMT"):
        started = datetime.fromisoformat(summary["startTimeGMT"].replace("Z", "+00:00"))
        values["started_at"] = started.replace(tzinfo=UTC) if started.tzinfo is None else started
    zone = payload.get("timeZoneUnitDTO") or {}
    if zone.get("timeZone") or zone.get("unitKey"):
        values["timezone"] = zone.get("timeZone") or zone["unitKey"]
    device = payload.get("deviceDTO") or {}
    device_id = payload.get("deviceId") or (payload.get("metadataDTO") or {}).get("deviceId")
    if device.get("displayName") or device_id:
        values["device"] = str(device.get("displayName") or device_id)
    return RunMetrics(**values)


def normalize_laps(payload: dict) -> list[RunLap]:
    result = []
    for row in payload.get("lapDTOs", []):
        speed = row.get("averageSpeed")
        result.append(
            RunLap(
                distance_m=row["distance"],
                duration_s=row["duration"],
                average_pace_s_km=1000 / speed if speed and speed > 0 else None,
                average_hr=row.get("averageHR"),
                max_hr=row.get("maxHR"),
                average_cadence_spm=row.get(
                    "averageRunCadence", row.get("averageRunningCadenceInStepsPerMinute")
                ),
                elevation_gain_m=row.get("elevationGain"),
                elevation_loss_m=row.get("elevationLoss"),
                average_power_w=row.get("averagePower", row.get("avgPower")),
                max_power_w=row.get("maxPower"),
            )
        )
    return result


def normalize_zones(payload: list[dict]) -> list[HeartRateZone]:
    # Never substitute current athlete zones for the bounds recorded with the run.
    rows = sorted(payload, key=lambda row: row["zoneNumber"])
    result = []
    for i, row in enumerate(rows):
        upper = row.get("zoneHighBoundary")
        if upper is None and i + 1 < len(rows):
            upper = rows[i + 1].get("zoneLowBoundary")
        result.append(
            HeartRateZone(
                zone=row["zoneNumber"],
                seconds=row["secsInZone"],
                lower_bpm=row.get("zoneLowBoundary"),
                upper_bpm=upper,
            )
        )
    return result


CHANNELS = {
    "sumDistance": "distance_m",
    "directHeartRate": "heart_rate_bpm",
    "directSpeed": "speed_m_s",
    "directRunCadence": "cadence_spm",
    "directDoubleCadence": "cadence_spm",
    "directElevation": "elevation_m",
    "directPower": "power_w",
    "directLatitude": "latitude_deg",
    "directLongitude": "longitude_deg",
}


def normalize_streams(payload: dict, *, gps: bool) -> RunStreams:
    descriptors = {
        d["key"]: d
        for d in payload.get("metricDescriptors", [])
        if isinstance(d.get("metricsIndex"), int) and d["metricsIndex"] >= 0
    }
    rows = payload.get("activityDetailMetrics", [])

    def column(key):
        descriptor = descriptors[key]
        index = descriptor["metricsIndex"]
        unit_data = descriptor.get("unit") or {}
        unit = (unit_data.get("key") or unit_data.get("unitKey") or "").lower()
        factor = {
            "cm": 0.01,
            "centimeter": 0.01,
            "km": 1000,
            "millisecond": 0.001,
            "ms": 0.001,
            "kph": 1 / 3.6,
            "km/h": 1 / 3.6,
        }.get(unit, 1)
        return [
            r["metrics"][index] * factor
            if index < len(r["metrics"]) and r["metrics"][index] is not None
            else None
            for r in rows
        ]

    if not rows:
        return RunStreams()
    if "directTimestamp" in descriptors:
        timestamps = column("directTimestamp")
        # Garmin directTimestamp is Unix milliseconds even if no unit is supplied.
        factor = 0.001 if timestamps[0] is not None and timestamps[0] > 1e11 else 1
        times = [(v - timestamps[0]) * factor if v is not None else None for v in timestamps]
    elif "sumElapsedDuration" in descriptors:
        times = column("sumElapsedDuration")
    else:
        raise ValueError("Garmin streams lack an elapsed time axis")
    if any(t is None for t in times):
        raise ValueError("Garmin streams contain missing timestamps")
    values = {"time_s": times}
    for key, name in CHANNELS.items():
        if key in descriptors and (gps or name not in {"latitude_deg", "longitude_deg"}):
            values[name] = column(key)
    return RunStreams(**values)


def kilometer_splits(streams: RunStreams) -> list[RunLap]:
    """Interpolate kilometer boundaries; weight sensor averages by elapsed seconds."""
    distance = streams.distance_m
    if not distance or len(distance) < 2 or any(v is None for v in distance):
        return []
    if distance != sorted(distance) or distance[0] != 0:
        return []
    result, accum = [], {}
    start_distance = 0.0
    next_boundary = 1000.0

    def finish(end_distance):
        nonlocal accum, start_distance
        duration = accum.get("duration", 0)
        length = end_distance - start_distance
        if length <= 0:
            return
        averages = {}
        for channel, field in (
            ("heart_rate_bpm", "average_hr"),
            ("cadence_spm", "average_cadence_spm"),
            ("power_w", "average_power_w"),
        ):
            weight = accum.get(channel + "_weight", 0)
            averages[field] = accum.get(channel, 0) / weight if weight else None
        result.append(
            RunLap(
                distance_m=length,
                duration_s=duration,
                average_pace_s_km=duration * 1000 / length if duration else None,
                max_hr=accum.get("heart_rate_bpm_max"),
                max_power_w=accum.get("power_w_max"),
                elevation_gain_m=accum.get("gain"),
                elevation_loss_m=accum.get("loss"),
                **averages,
            )
        )
        start_distance, accum = end_distance, {}

    for i in range(1, len(distance)):
        lo, hi = distance[i - 1], distance[i]
        elapsed = streams.time_s[i] - streams.time_s[i - 1]
        cursor = lo
        while True:
            end = min(hi, next_boundary)
            fraction = (end - cursor) / (hi - lo) if hi > lo else 1
            seconds = elapsed * fraction
            accum["duration"] = accum.get("duration", 0) + seconds
            for channel in ("heart_rate_bpm", "cadence_spm", "power_w"):
                data = getattr(streams, channel)
                if data and data[i] is not None:
                    accum[channel] = accum.get(channel, 0) + data[i] * seconds
                    accum[channel + "_weight"] = accum.get(channel + "_weight", 0) + seconds
                    accum[channel + "_max"] = max(accum.get(channel + "_max", 0), data[i])
            elevation = streams.elevation_m
            if elevation and elevation[i] is not None and elevation[i - 1] is not None:
                change = (elevation[i] - elevation[i - 1]) * fraction
                accum["gain"] = accum.get("gain", 0) + max(0, change)
                accum["loss"] = accum.get("loss", 0) + max(0, -change)
            if end == next_boundary and end < distance[-1]:
                finish(end)
                next_boundary += 1000
            if end >= hi:
                break
            cursor = end
    finish(distance[-1])
    return result


def fit_bytes(download: bytes) -> bytes:
    if zipfile.is_zipfile(io.BytesIO(download)):
        with zipfile.ZipFile(io.BytesIO(download)) as archive:
            entries = [i for i in archive.infolist() if i.filename.lower().endswith(".fit")]
            if len(entries) != 1 or entries[0].file_size > 64 * 1024 * 1024:
                raise ValueError("Original archive must contain one FIT file of at most 64 MiB")
            download = archive.read(entries[0])
    if (
        len(download) < 14
        or len(download) > 64 * 1024 * 1024
        or download[0] not in {12, 14}
        or download[8:12] != b".FIT"
        or len(download) != download[0] + struct.unpack_from("<I", download, 4)[0] + 2
    ):
        raise ValueError("Invalid original FIT file")
    return download


def archive_fit(activity_id: str, download: bytes) -> str:
    data = fit_bytes(download)
    directory = Path(
        os.getenv("STRIDE_COACH_FIT_DIR", "~/.local/share/stride-coach/fit")
    ).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = hashlib.sha256(activity_id.encode()).hexdigest() + ".fit"
    path = directory / name
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("Existing original FIT differs; archive was preserved")
        return name
    fd, temporary = tempfile.mkstemp(prefix=".capture-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Link creates atomically without replacing an existing archive.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError("Existing original FIT differs; archive was preserved") from None
    finally:
        os.unlink(temporary)
    return name


def capture_pending(store, client, *, limit=20, include_legacy=False) -> BackfillResult:
    if not 1 <= limit <= 1000:
        raise ValueError("Detail batch limit must be 1 to 1000")
    gps = store_gps()
    result = BackfillResult()
    # Shared write lock also serializes detail requests across CLI and API workers.
    with store.lock():
        ids = pending_ids(store, limit, include_legacy=include_legacy)
        for activity_id in ids:
            mark_attempt(store, activity_id)
            try:
                activity, download = client.activity_detail(activity_id, gps=gps)
                if activity.id != activity_id:
                    raise ValueError("Garmin activity ID did not match")
                fit_name = archive_fit(activity_id, download) if gps else None
                with store.transaction() as session:
                    save_details(session, activity, gps=gps)
                mark_attempt(store, activity_id, complete=True, fit_name=fit_name)
                result.completed += 1
            except (
                GarminError,
                ValueError,
                OSError,
                zipfile.BadZipFile,
                KeyError,
                TypeError,
                AttributeError,
            ):
                # Avoid persisting payloads, locations or upstream exception bodies.
                mark_attempt(store, activity_id, error="Detail capture failed; retry backfill.")
                result.failed += 1
                # Stop this batch on failure, including rate limits. No tight retry loop.
                break
        result.remaining = len(pending_ids(store, 1000000, include_legacy=include_legacy))
    return result


def fetch_detail(client, activity_id: str, *, gps: bool):
    from .garmin import normalize_activity

    delay = float(os.getenv("STRIDE_COACH_DETAIL_DELAY_SECONDS", "1"))
    if not 0.1 <= delay <= 60:
        raise ValueError("Detail request delay must be between 0.1 and 60 seconds")

    def request(method, *args, **kwargs):
        time.sleep(delay)
        return client._call(method, *args, **kwargs)

    summary = request(client.api.get_activity, activity_id)
    combined = {**summary, **summary.get("summaryDTO", {})}
    combined.setdefault("activityId", activity_id)
    activity = normalize_activity(combined)
    activity.raw_summary = summary if gps else None
    activity.metrics = normalize_metrics(summary)
    activity.laps = normalize_laps(request(client.api.get_activity_splits, activity_id))
    activity.hr_zones = normalize_zones(
        request(client.api.get_activity_hr_in_timezones, activity_id)
    )
    activity.streams = normalize_streams(
        request(client.api.get_activity_details, activity_id, maxchart=200000, maxpoly=0), gps=gps
    )
    laps = activity.laps
    activity.splits = (
        laps
        if laps
        and all(lap.distance_m == 1000 for lap in laps[:-1])
        and 0 < laps[-1].distance_m <= 1000
        else kilometer_splits(activity.streams)
    )
    download = (
        request(
            client.api.download_activity,
            activity_id,
            dl_fmt=client.api.ActivityDownloadFormat.ORIGINAL,
        )
        if gps
        else None
    )
    return activity, download
