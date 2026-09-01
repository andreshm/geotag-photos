"""auto_tagger.py — propagate GPS to photos taken close in time to an anchor."""

from __future__ import annotations

import bisect
import logging
from datetime import timedelta, datetime
from typing import Optional

from .photo_item import PhotoItem

log = logging.getLogger(__name__)


def _interpolate_gps(
    t: datetime,
    t1: datetime,
    gps1: tuple[float, float],
    t2: datetime,
    gps2: tuple[float, float],
) -> tuple[float, float]:
    """Linear time-based interpolation between two GPS coordinate points."""
    total_seconds = (t2 - t1).total_seconds()
    if total_seconds <= 0:
        return gps1

    ratio = (t - t1).total_seconds() / total_seconds
    ratio = max(0.0, min(1.0, ratio))

    lat = gps1[0] + (gps2[0] - gps1[0]) * ratio
    lon = gps1[1] + (gps2[1] - gps1[1]) * ratio
    return (lat, lon)


def _find_bounding_anchors(
    dt: datetime,
    anchor_times: list[datetime],
    anchors: list[PhotoItem],
) -> tuple[Optional[PhotoItem], Optional[PhotoItem]]:
    """Find the anchor immediately before and immediately after *dt*."""
    if not anchors:
        return None, None

    idx = bisect.bisect_left(anchor_times, dt)
    before = anchors[idx - 1] if idx > 0 else None
    after = anchors[idx] if idx < len(anchors) else None
    return before, after


def auto_tag_by_time(
    all_items: list[PhotoItem],
    gap_minutes: float = 3.0,
    use_interpolation: bool = True,
) -> list[PhotoItem]:
    """Assign pending GPS to un-tagged photos close in time to tagged anchors.

    If *use_interpolation* is True and a photo is flanked before & after by anchors
    within the time gap, coordinates are linearly interpolated.
    Otherwise, nearest anchor GPS is assigned.
    """
    gap = timedelta(minutes=gap_minutes)

    anchors    = [i for i in all_items if i.date_taken and i.effective_gps is not None]
    candidates = [i for i in all_items if i.date_taken and i.effective_gps is None]

    if not anchors:
        log.info("Auto-tag: no geotagged anchors found.")
        return []

    # Sort anchors by date for fast binary search
    anchors.sort(key=lambda i: i.date_taken)
    anchor_times = [i.date_taken for i in anchors]

    tagged: list[PhotoItem] = []
    for cand in candidates:
        dt = cand.date_taken
        before, after = _find_bounding_anchors(dt, anchor_times, anchors)

        d_before = abs(dt - before.date_taken) if before else timedelta.max
        d_after  = abs(dt - after.date_taken) if after else timedelta.max

        if before and after and d_before <= gap and d_after <= gap and use_interpolation:
            # Interpolate between flanking anchors
            gps1 = before.effective_gps
            gps2 = after.effective_gps
            if gps1 and gps2:
                cand.pending.gps = _interpolate_gps(dt, before.date_taken, gps1, after.date_taken, gps2)
                tagged.append(cand)
                continue

        # Fallback to nearest single anchor
        best_anchor = before if d_before <= d_after else after
        best_delta  = min(d_before, d_after)

        if best_anchor and best_delta <= gap:
            cand.pending.gps = best_anchor.effective_gps
            tagged.append(cand)

    log.info("Auto-tag: %d / %d candidates tagged (gap=%.1f min)",
             len(tagged), len(candidates), gap_minutes)
    return tagged


def preview_auto_tag(
    all_items: list[PhotoItem],
    gap_minutes: float = 3.0,
    use_interpolation: bool = True,
) -> list[tuple[PhotoItem, tuple[float, float], str]]:
    """Dry-run: returns (item, (lat, lon), description) tuples without mutating state."""
    gap = timedelta(minutes=gap_minutes)

    anchors    = [i for i in all_items if i.date_taken and i.effective_gps is not None]
    candidates = [i for i in all_items if i.date_taken and i.effective_gps is None]

    if not anchors:
        return []

    anchors.sort(key=lambda i: i.date_taken)
    anchor_times = [i.date_taken for i in anchors]

    results = []
    for cand in candidates:
        dt = cand.date_taken
        before, after = _find_bounding_anchors(dt, anchor_times, anchors)

        d_before = abs(dt - before.date_taken) if before else timedelta.max
        d_after  = abs(dt - after.date_taken) if after else timedelta.max

        if before and after and d_before <= gap and d_after <= gap and use_interpolation:
            gps1 = before.effective_gps
            gps2 = after.effective_gps
            if gps1 and gps2:
                interp = _interpolate_gps(dt, before.date_taken, gps1, after.date_taken, gps2)
                desc = f"Interpolated between {before.display_name} & {after.display_name}"
                results.append((cand, interp, desc))
                continue

        best_anchor = before if d_before <= d_after else after
        best_delta  = min(d_before, d_after)

        if best_anchor and best_delta <= gap:
            gps = best_anchor.effective_gps
            if gps:
                mins = best_delta.total_seconds() / 60.0
                desc = f"Matched to {best_anchor.display_name} ({mins:.1f}m gap)"
                results.append((cand, gps, desc))

    return results
