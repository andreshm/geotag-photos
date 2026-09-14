"""track_service.py — Ingestion, parsing, and matching of GPS tracks (OwnTracks, GPX, GeoJSON).

Provides:
- TrackPoint & TrackMatchResult data structures
- Parsers for OwnTracks (.json, .rec), GPX (.gpx), and GeoJSON (.geojson)
- OwnTracks Recorder REST API client
- Time-based binary-search photo matching with linear interpolation and camera time offset
"""

from __future__ import annotations

import base64
import bisect
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Optional, Union, Sequence
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from .photo_item import PhotoItem

log = logging.getLogger(__name__)

# ── Settings Keys for QSettings (stored locally in OS user registry / app data) ─
SETTINGS_OWNTRACKS_URL       = "track/owntracks_url"
SETTINGS_OWNTRACKS_USER      = "track/owntracks_user"
SETTINGS_OWNTRACKS_DEVICE    = "track/owntracks_device"
SETTINGS_OWNTRACKS_AUTH_TYPE = "track/owntracks_auth_type"  # "none", "basic", "bearer"
SETTINGS_OWNTRACKS_AUTH_USER = "track/owntracks_auth_user"
SETTINGS_OWNTRACKS_AUTH_PASS = "track/owntracks_auth_pass"
SETTINGS_TRACK_OFFSET_SECS   = "track/offset_seconds"
SETTINGS_TRACK_TOLERANCE_MIN = "track/tolerance_minutes"
SETTINGS_TRACK_INTERPOLATE   = "track/use_interpolation"
SETTINGS_TRACK_MAX_ACCURACY  = "track/max_accuracy"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TrackPoint:
    """A single geographic location point recorded at a specific UTC timestamp."""
    timestamp: datetime  # Timezone-aware UTC datetime
    lat: float
    lon: float
    alt: Optional[float] = None       # Altitude / elevation in meters
    accuracy: Optional[float] = None  # Horizontal accuracy in meters (acc in OwnTracks)
    velocity: Optional[float] = None  # Speed in km/h or m/s


@dataclass
class MatchedPhoto:
    """Details of a photo matched against the GPS track."""
    photo: PhotoItem
    photo_dt: datetime           # Original photo date taken
    adjusted_dt: datetime        # Photo date taken after applying camera time offset
    lat: float
    lon: float
    alt: Optional[float] = None
    delta_seconds: float = 0.0   # Absolute difference between adjusted time and nearest fix
    match_type: str = "interpolated"  # "interpolated" or "nearest"


@dataclass
class TrackMatchResult:
    """Aggregated report of a track matching run."""
    total_photos: int
    matched: list[MatchedPhoto] = field(default_factory=list)
    unmatched: list[PhotoItem] = field(default_factory=list)
    track_point_count: int = 0
    track_start: Optional[datetime] = None
    track_end: Optional[datetime] = None

    @property
    def matched_count(self) -> int:
        return len(self.matched)

    @property
    def match_percentage(self) -> float:
        if self.total_photos == 0:
            return 0.0
        return (self.matched_count / self.total_photos) * 100.0


# ---------------------------------------------------------------------------
# Timestamp Normalization Utilities
# ---------------------------------------------------------------------------

def _to_utc_datetime(val: Union[int, float, str, datetime]) -> Optional[datetime]:
    """Convert epoch timestamp, ISO string, or naive/aware datetime to UTC datetime."""
    if val is None:
        return None

    if isinstance(val, (int, float)):
        # Epoch seconds or milliseconds
        if val > 1e11:  # Milliseconds
            val = val / 1000.0
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None

    if isinstance(val, datetime):
        if val.tzinfo is None:
            # Assume UTC if naive
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)

    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None

        # Check if purely numeric epoch
        if re.match(r"^\d+(?:\.\d+)?$", val):
            try:
                num = float(val)
                if num > 1e11:
                    num /= 1000.0
                return datetime.fromtimestamp(num, tz=timezone.utc)
            except Exception:
                pass

        # Try standard ISO formats
        iso_str = val.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # Fallback date patterns
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y%m%d_%H%M%S",
            "%Y%m%d-%H%M%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(val, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

    return None


# ---------------------------------------------------------------------------
# Track Parsers
# ---------------------------------------------------------------------------

class TrackParser:
    """Parses various GPS track formats into a list of TrackPoint objects."""

    @staticmethod
    def parse_owntracks_json(data: Union[str, bytes, list, dict]) -> list[TrackPoint]:
        """Parses OwnTracks JSON exports or location arrays.

        Supported formats:
        - Single location object: `{"_type": "location", "lat": ..., "lon": ..., "tst": ...}`
        - Array of location objects: `[{"lat": ..., "lon": ..., "tst": ...}, ...]`
        - Wrapper object with `locations` or `data` key.
        """
        if isinstance(data, (str, bytes)):
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            try:
                data = json.loads(data)
            except Exception as e:
                log.warning("Failed to parse JSON string: %s", e)
                return []

        raw_items: list[dict] = []
        if isinstance(data, list):
            raw_items = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            if "locations" in data and isinstance(data["locations"], list):
                raw_items = [x for x in data["locations"] if isinstance(x, dict)]
            elif "data" in data and isinstance(data["data"], list):
                raw_items = [x for x in data["data"] if isinstance(x, dict)]
            else:
                raw_items = [data]

        points: list[TrackPoint] = []
        for item in raw_items:
            lat = item.get("lat") or item.get("latitude")
            lon = item.get("lon") or item.get("longitude") or item.get("lng")
            tst = item.get("tst") or item.get("timestamp") or item.get("created_at") or item.get("time")

            if lat is None or lon is None or tst is None:
                continue

            try:
                lat_f = float(lat)
                lon_f = float(lon)
                dt = _to_utc_datetime(tst)
                if dt is None:
                    continue
                if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
                    continue

                alt = float(item["alt"]) if "alt" in item and item["alt"] is not None else None
                acc = float(item["acc"]) if "acc" in item and item["acc"] is not None else None
                vel = float(item["vel"]) if "vel" in item and item["vel"] is not None else None

                points.append(TrackPoint(
                    timestamp=dt,
                    lat=lat_f,
                    lon=lon_f,
                    alt=alt,
                    accuracy=acc,
                    velocity=vel,
                ))
            except (ValueError, TypeError):
                continue

        points.sort(key=lambda p: p.timestamp)
        return points

    @staticmethod
    def parse_owntracks_rec(text: str) -> list[TrackPoint]:
        """Parses OwnTracks Recorder (.rec) log files.

        Format example:
        2026-09-13T18:00:00Z user device {"_type":"location","lat":51.5,"lon":-0.1,"tst":1789408800,...}
        or raw JSON lines.
        """
        points: list[TrackPoint] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Look for JSON object in line
            idx = line.find("{")
            if idx != -1:
                json_part = line[idx:]
                try:
                    obj = json.loads(json_part)
                    if isinstance(obj, dict):
                        # If tst is missing from json, try parsing timestamp prefix in the line
                        if "tst" not in obj and idx > 0:
                            prefix = line[:idx].strip().split()
                            if prefix:
                                dt_prefix = _to_utc_datetime(prefix[0])
                                if dt_prefix:
                                    obj["tst"] = int(dt_prefix.timestamp())
                        pts = TrackParser.parse_owntracks_json([obj])
                        points.extend(pts)
                except Exception:
                    pass

        points.sort(key=lambda p: p.timestamp)
        return points

    @staticmethod
    def parse_gpx(content: Union[str, bytes]) -> list[TrackPoint]:
        """Parses GPX XML track files (<trkpt> and <wpt>)."""
        if isinstance(content, str):
            content = content.encode("utf-8", errors="replace")

        points: list[TrackPoint] = []
        try:
            root = ET.fromstring(content)
            # Remove namespace prefixes for easy searching
            for elem in root.iter():
                if "}" in elem.tag:
                    elem.tag = elem.tag.split("}", 1)[1]

            for pt in root.iter():
                if pt.tag in ("trkpt", "wpt", "rtept"):
                    lat_str = pt.attrib.get("lat")
                    lon_str = pt.attrib.get("lon")
                    if not lat_str or not lon_str:
                        continue

                    time_elem = pt.find("time")
                    if time_elem is None or not time_elem.text:
                        continue

                    dt = _to_utc_datetime(time_elem.text)
                    if dt is None:
                        continue

                    try:
                        lat_f = float(lat_str)
                        lon_f = float(lon_str)
                        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
                            continue

                        ele_elem = pt.find("ele")
                        alt = float(ele_elem.text) if ele_elem is not None and ele_elem.text else None

                        speed_elem = pt.find("speed")
                        vel = float(speed_elem.text) if speed_elem is not None and speed_elem.text else None

                        hdop_elem = pt.find("hdop")
                        acc = float(hdop_elem.text) * 5.0 if hdop_elem is not None and hdop_elem.text else None

                        points.append(TrackPoint(
                            timestamp=dt,
                            lat=lat_f,
                            lon=lon_f,
                            alt=alt,
                            accuracy=acc,
                            velocity=vel,
                        ))
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            log.warning("GPX parse error: %s", e)

        points.sort(key=lambda p: p.timestamp)
        return points

    @staticmethod
    def parse_geojson(data: Union[str, bytes, dict]) -> list[TrackPoint]:
        """Parses GeoJSON FeatureCollection with Point/LineString features and timestamps."""
        if isinstance(data, (str, bytes)):
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            try:
                data = json.loads(data)
            except Exception as e:
                log.warning("Failed to parse GeoJSON: %s", e)
                return []

        if not isinstance(data, dict):
            return []

        points: list[TrackPoint] = []
        features = data.get("features", [])
        if not features and data.get("type") == "Feature":
            features = [data]

        for feat in features:
            geom = feat.get("geometry", {})
            props = feat.get("properties", {}) or {}
            g_type = geom.get("type", "")
            coords = geom.get("coordinates", [])

            if g_type == "Point" and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
                alt = coords[2] if len(coords) >= 3 else None
                tst = props.get("timestamp") or props.get("time") or props.get("tst") or props.get("coordTimes")
                dt = _to_utc_datetime(tst)
                if dt and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    points.append(TrackPoint(
                        timestamp=dt,
                        lat=float(lat),
                        lon=float(lon),
                        alt=float(alt) if alt is not None else None,
                        accuracy=float(props.get("acc")) if "acc" in props else None,
                    ))

            elif g_type == "LineString" and coords:
                coord_times = props.get("coordTimes", [])
                for idx, c in enumerate(coords):
                    if len(c) >= 2:
                        lon, lat = c[0], c[1]
                        alt = c[2] if len(c) >= 3 else None
                        tst = coord_times[idx] if idx < len(coord_times) else None
                        dt = _to_utc_datetime(tst)
                        if dt and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                            points.append(TrackPoint(
                                timestamp=dt,
                                lat=float(lat),
                                lon=float(lon),
                                alt=float(alt) if alt is not None else None,
                            ))

        points.sort(key=lambda p: p.timestamp)
        return points

    @classmethod
    def load_track_file(cls, file_path: Union[str, Path]) -> list[TrackPoint]:
        """Auto-detects format from file extension and content, returning sorted TrackPoints."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"Track file not found: {file_path}")

        suffix = p.suffix.lower()
        content_bytes = p.read_bytes()
        content_text = content_bytes.decode("utf-8", errors="replace")

        if suffix in (".gpx", ".xml"):
            return cls.parse_gpx(content_bytes)

        if suffix == ".rec":
            return cls.parse_owntracks_rec(content_text)

        if suffix in (".geojson", ".json"):
            # Try GeoJSON first if structure looks like FeatureCollection
            if "features" in content_text or '"Feature"' in content_text:
                pts = cls.parse_geojson(content_text)
                if pts:
                    return pts
            # Fall back to OwnTracks JSON parser
            pts = cls.parse_owntracks_json(content_text)
            if pts:
                return pts
            # Fall back to rec parser in case it's a .rec saved as .json
            return cls.parse_owntracks_rec(content_text)

        # Fallback by content inspection
        if "<gpx" in content_text or "<trkpt" in content_text:
            return cls.parse_gpx(content_bytes)

        if "{" in content_text:
            pts = cls.parse_owntracks_json(content_text)
            if pts:
                return pts
            return cls.parse_owntracks_rec(content_text)

        return []


# ---------------------------------------------------------------------------
# OwnTracks Server REST Client
# ---------------------------------------------------------------------------

class OwnTracksClient:
    """Client for querying an OwnTracks Recorder HTTP server (/api/0/locations)."""

    @classmethod
    def fetch_locations(
        cls,
        server_url: str,
        user: str,
        device: str,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        auth_type: str = "none",
        username: str = "",
        password_or_token: str = "",
        timeout: int = 30,
    ) -> list[TrackPoint]:
        """Queries the OwnTracks Recorder API for location points in a given time window.

        API Endpoint:
        GET {server_url}/api/0/locations?user={user}&device={device}&from={from}&to={to}
        """
        server_url = server_url.strip().rstrip("/")
        if not server_url.startswith(("http://", "https://")):
            server_url = "http://" + server_url

        # OwnTracks Recorder uses /api/0/locations
        endpoint = f"{server_url}/api/0/locations"

        query_params = []
        if user:
            query_params.append(f"user={urllib.parse.quote(user.strip())}")
        if device:
            query_params.append(f"device={urllib.parse.quote(device.strip())}")

        if from_dt:
            from_utc = _to_utc_datetime(from_dt)
            if from_utc:
                query_params.append(f"from={urllib.parse.quote(from_utc.strftime('%Y-%m-%dT%H:%M:%SZ'))}")

        if to_dt:
            to_utc = _to_utc_datetime(to_dt)
            if to_utc:
                query_params.append(f"to={urllib.parse.quote(to_utc.strftime('%Y-%m-%dT%H:%M:%SZ'))}")

        if query_params:
            endpoint += "?" + "&".join(query_params)

        headers = {
            "Accept": "application/json",
            "User-Agent": "GeoTagStudioPRO/2.0 (OwnTracks Client)",
        }

        # Handle Authentication
        auth_type_clean = (auth_type or "none").lower()
        if auth_type_clean == "basic" and (username or password_or_token):
            auth_str = f"{username}:{password_or_token}"
            b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {b64_auth}"
        elif auth_type_clean == "bearer" and password_or_token:
            headers["Authorization"] = f"Bearer {password_or_token.strip()}"

        req = urllib.request.Request(endpoint, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_text = resp.read().decode("utf-8", errors="replace")
                points = TrackParser.parse_owntracks_json(resp_text)
                if not points:
                    # Try .rec parsing in case response is raw lines
                    points = TrackParser.parse_owntracks_rec(resp_text)
                return points
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise ConnectionError(f"OwnTracks Server HTTP Error ({exc.code}): {exc.reason}\n{err_body}")
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Could not connect to OwnTracks Server at {server_url}: {exc.reason}")
        except Exception as exc:
            raise ConnectionError(f"Failed to fetch OwnTracks data: {exc}")


# ---------------------------------------------------------------------------
# Matching & Interpolation Engine
# ---------------------------------------------------------------------------

def _interpolate_coords(
    t: datetime,
    p1: TrackPoint,
    p2: TrackPoint,
) -> tuple[float, float, Optional[float]]:
    """Linear time interpolation between two track points (lat, lon, alt)."""
    t1 = p1.timestamp
    t2 = p2.timestamp
    total_seconds = (t2 - t1).total_seconds()
    if total_seconds <= 0:
        return p1.lat, p1.lon, p1.alt

    ratio = (t - t1).total_seconds() / total_seconds
    ratio = max(0.0, min(1.0, ratio))

    lat = p1.lat + (p2.lat - p1.lat) * ratio
    lon = p1.lon + (p2.lon - p1.lon) * ratio

    alt: Optional[float] = None
    if p1.alt is not None and p2.alt is not None:
        alt = p1.alt + (p2.alt - p1.alt) * ratio
    elif p1.alt is not None:
        alt = p1.alt
    elif p2.alt is not None:
        alt = p2.alt

    return lat, lon, alt


class TrackMatcher:
    """Matches photos to a GPS track using time correlation and interpolation."""

    @classmethod
    def match_photos(
        cls,
        photos: Sequence[PhotoItem],
        track_points: Sequence[TrackPoint],
        time_offset_seconds: int = 0,
        tolerance_seconds: int = 600,
        use_interpolation: bool = True,
        max_accuracy_meters: Optional[float] = None,
    ) -> TrackMatchResult:
        """Matches a list of photos to GPS track points based on Date Taken + time offset.

        Parameters:
        - `photos`: sequence of PhotoItem objects with `date_taken`
        - `track_points`: sequence of TrackPoint objects
        - `time_offset_seconds`: camera clock offset (e.g. +3600 for UTC+1 or drift correction)
        - `tolerance_seconds`: max allowed time delta to accept a track match (default: 600s = 10 min)
        - `use_interpolation`: whether to linearly interpolate coordinates between flanking points
        - `max_accuracy_meters`: optional filter to ignore fixes with poor GPS accuracy (e.g. > 50m)
        """
        valid_photos = [p for p in photos if p.date_taken is not None]
        if not track_points:
            return TrackMatchResult(
                total_photos=len(valid_photos),
                unmatched=list(valid_photos),
            )

        # Filter track points by accuracy if specified
        points = list(track_points)
        if max_accuracy_meters is not None and max_accuracy_meters > 0:
            points = [p for p in points if p.accuracy is None or p.accuracy <= max_accuracy_meters]

        if not points:
            return TrackMatchResult(
                total_photos=len(valid_photos),
                unmatched=list(valid_photos),
            )

        # Ensure points are sorted by timestamp
        points.sort(key=lambda p: p.timestamp)
        point_times = [p.timestamp for p in points]

        matched_list: list[MatchedPhoto] = []
        unmatched_list: list[PhotoItem] = []
        tol_delta = timedelta(seconds=tolerance_seconds)
        offset_delta = timedelta(seconds=time_offset_seconds)

        for photo in valid_photos:
            raw_dt = photo.date_taken
            if raw_dt is None:
                unmatched_list.append(photo)
                continue

            # Convert photo naive datetime to UTC and apply time offset
            photo_utc = raw_dt.replace(tzinfo=timezone.utc) if raw_dt.tzinfo is None else raw_dt.astimezone(timezone.utc)
            adjusted_dt = photo_utc + offset_delta

            # Binary search for closest points
            idx = bisect.bisect_left(point_times, adjusted_dt)
            p_before = points[idx - 1] if idx > 0 else None
            p_after  = points[idx] if idx < len(points) else None

            d_before = abs(adjusted_dt - p_before.timestamp) if p_before else timedelta.max
            d_after  = abs(adjusted_dt - p_after.timestamp)  if p_after  else timedelta.max

            # 1. Try Linear Interpolation if flanked on both sides within tolerance
            if p_before and p_after and d_before <= tol_delta and d_after <= tol_delta and use_interpolation:
                lat, lon, alt = _interpolate_coords(adjusted_dt, p_before, p_after)
                min_delta = min(d_before.total_seconds(), d_after.total_seconds())
                matched_list.append(MatchedPhoto(
                    photo=photo,
                    photo_dt=raw_dt,
                    adjusted_dt=adjusted_dt,
                    lat=lat,
                    lon=lon,
                    alt=alt,
                    delta_seconds=min_delta,
                    match_type="interpolated",
                ))
                continue

            # 2. Nearest point fallback
            best_pt = p_before if d_before <= d_after else p_after
            best_delta = min(d_before, d_after)

            if best_pt and best_delta <= tol_delta:
                matched_list.append(MatchedPhoto(
                    photo=photo,
                    photo_dt=raw_dt,
                    adjusted_dt=adjusted_dt,
                    lat=best_pt.lat,
                    lon=best_pt.lon,
                    alt=best_pt.alt,
                    delta_seconds=best_delta.total_seconds(),
                    match_type="nearest",
                ))
            else:
                unmatched_list.append(photo)

        return TrackMatchResult(
            total_photos=len(valid_photos),
            matched=matched_list,
            unmatched=unmatched_list,
            track_point_count=len(points),
            track_start=points[0].timestamp if points else None,
            track_end=points[-1].timestamp if points else None,
        )
