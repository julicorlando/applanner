"""Time grid for the day and week views: rows of 15 minutes, events placed by start and length.

Everything here is presentation: positions are in slots (15 min) from the first hour shown, and events
that overlap in the same day share the width side by side.
"""
from datetime import datetime, time, timedelta

SLOT = 15
# Calm, readable fills; each service keeps the same colour everywhere in the agenda.
PALETTE = ("#2563eb", "#e4572e", "#16a34a", "#9333ea", "#0891b2", "#d97706", "#db2777", "#4d7c0f", "#7c3aed", "#0f766e")


def colour(service_id):
    return PALETTE[(service_id or 0) % len(PALETTE)]


def hour_range(columns, tz, default=(8, 18)):
    first, last = default
    for column in columns:
        for row in column["rows"]:
            first = min(first, row.starts_at.astimezone(tz).hour)
            end = row.ends_at.astimezone(tz)
            last = max(last, end.hour + (1 if end.minute else 0))
        for window in column["windows"]:
            first = min(first, window["start"].hour)
            last = max(last, window["end"].hour + (1 if window["end"].minute else 0))
    return max(0, first), min(24, max(last, first + 1))


def _place(day, start, end, tz, first_hour, last_hour):
    origin = datetime.combine(day, time(first_hour), tz)
    limit = datetime.combine(day, time.min, tz) + timedelta(hours=last_hour)
    start, end = max(start.astimezone(tz), origin), min(end.astimezone(tz), limit)
    if end <= start:
        return None
    top = (start - origin).total_seconds() / 60 / SLOT
    return top, max((end - start).total_seconds() / 60 / SLOT, 1)


def _lanes(items):
    """Side-by-side columns for overlapping events (greedy, per cluster of overlaps)."""
    items.sort(key=lambda item: (item["top"], -item["height"]))
    cluster, cluster_end, ends = [], -1, []
    for item in items:
        if item["top"] >= cluster_end and cluster:
            for done in cluster:
                done["lanes"] = len(ends)
            cluster, ends = [], []
        lane = next((i for i, end in enumerate(ends) if end <= item["top"]), None)
        if lane is None:
            lane = len(ends)
            ends.append(0)
        ends[lane] = item["top"] + item["height"]
        item["lane"] = lane
        cluster.append(item)
        cluster_end = max(cluster_end, item["top"] + item["height"])
    for done in cluster:
        done["lanes"] = max(len(ends), 1)
    return items


def now_line(tz, first_hour, last_hour):
    from django.utils import timezone
    now = timezone.now().astimezone(tz)
    minutes = (now.hour - first_hour) * 60 + now.minute
    return minutes / SLOT if 0 <= minutes < (last_hour - first_hour) * 60 else None


def build(columns, tz, first_hour, last_hour):
    """Adds positioned 'events', 'free' and 'off' lists to each day column and returns the hour labels."""
    for column in columns:
        day, events = column["day"], []
        for row in column["rows"]:
            spot = _place(day, row.starts_at, row.ends_at, tz, first_hour, last_hour)
            if spot:
                events.append({"row": row, "top": spot[0], "height": spot[1],
                               "colour": colour(getattr(row, "service_id", None)), "lane": 0, "lanes": 1})
        column["events"] = _lanes(events)
        for item in column["events"]:
            item["width"] = 100 / item["lanes"]
            item["left"] = item["lane"] * item["width"]
        column["free"] = []
        for window in column["windows"]:
            spot = _place(day, window["start"], window["end"], tz, first_hour, last_hour)
            if spot:
                column["free"].append({**window, "top": spot[0], "height": spot[1]})
        column["off"] = []
        for block in column["blocks"]:
            spot = _place(day, block.starts_at, block.ends_at, tz, first_hour, last_hour)
            if spot:
                column["off"].append({"row": block, "top": spot[0], "height": spot[1]})
    labels = []
    for hour in range(first_hour, last_hour):
        for minute in (0, 15, 30, 45):
            labels.append({"text": f"{hour:02d}:{minute:02d}", "full": minute == 0})
    return labels
