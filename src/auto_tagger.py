"""auto_tagger.py — propagate GPS to photos taken close in time to an anchor."""

from __future__ import annotations

import bisect
import logging
from datetime import timedelta
from typing import Optional

from .photo_item import PhotoItem

log = logging.getLogger(__name__)


def _nearest_anchor(
    dt,
    anchor_times: list,     # sorted list of datetime objects
    anchors: list[PhotoItem],
) -> tuple[Optional[PhotoItem], timedelta]:
    """Binary-search the sorted anchor list for the closest entry to *dt*.

    Returns (anchor_item, |delta|) — O(log n) per call.
    """
    if not anchors:
        return None, timedelta.max

    idx = bisect.bisect_left(anchor_times, dt)

    candidates: list[tuple[timedelta, PhotoItem]] = []
    for i in (idx - 1, idx):
        if 0 <= i < len(anchors):
            delta = abs(dt - anchor_times[i])
            candidates.append((delta, anchors[i]))

    if not candidates:
        return None, timedelta.max

    best_delta, best_anchor = min(candidates, key=lambda x: x[0])
    return best_anchor, best_delta


def auto_tag_by_time(
    all_items: list[PhotoItem],
    gap_minutes: float = 3.0,
) -> list[PhotoItem]:
    """Assign pending GPS to un-tagged photos close in time to a tagged anchor.

    Works in O(n log n) by sorting anchors once and binary-searching per candidate.
    Only photos with ``date_taken`` set are considered.

    Returns the list of items newly staged (for UI feedback).
    """
    gap = timedelta(minutes=gap_minutes)

    anchors    = [i for i in all_items if i.date_taken and i.effective_gps is not None]
    candidates = [i for i in all_items if i.date_taken and i.effective_gps is None]

    if not anchors:
        log.info("Auto-tag: no geotagged anchors found.")
        return []

    # Sort anchors by date for binary search
    anchors.sort(key=lambda i: i.date_taken)          # type: ignore[arg-type]
    anchor_times = [i.date_taken for i in anchors]    # parallel list of datetimes

    tagged: list[PhotoItem] = []
    for cand in candidates:
        best_anchor, best_delta = _nearest_anchor(cand.date_taken, anchor_times, anchors)
        if best_anchor and best_delta <= gap:
            gps = best_anchor.effective_gps
            cand.pending.gps = gps
            tagged.append(cand)
            log.debug(
                "Auto-tagged %-30s → %+.6f, %+.6f  (Δ%s from %s)",
                cand.display_name,
                gps[0], gps[1],          # type: ignore[index]
                best_delta,
                best_anchor.display_name,
            )

    log.info("Auto-tag: %d / %d candidates tagged (gap=%.1f min)",
             len(tagged), len(candidates), gap_minutes)
    return tagged


def preview_auto_tag(
    all_items: list[PhotoItem],
    gap_minutes: float = 3.0,
) -> list[tuple[PhotoItem, tuple[float, float], str]]:
    """Dry-run: return (item, (lat, lon), anchor_name) tuples without mutating."""
    gap = timedelta(minutes=gap_minutes)

    anchors    = [i for i in all_items if i.date_taken and i.effective_gps is not None]
    candidates = [i for i in all_items if i.date_taken and i.effective_gps is None]

    if not anchors:
        return []

    anchors.sort(key=lambda i: i.date_taken)           # type: ignore[arg-type]
    anchor_times = [i.date_taken for i in anchors]

    result = []
    for cand in candidates:
        best_anchor, best_delta = _nearest_anchor(cand.date_taken, anchor_times, anchors)
        if best_anchor and best_delta <= gap:
            result.append((cand, best_anchor.effective_gps, best_anchor.display_name))  # type: ignore[arg-type]

    return result
