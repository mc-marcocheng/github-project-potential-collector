from __future__ import annotations

from datetime import datetime, timedelta

LANDMARK_OFFSET_HOURS = 24
LANDMARK_OFFSET = timedelta(hours=LANDMARK_OFFSET_HOURS)
HORIZON_DAYS = (30, 90, 180)


def readiness_landmark(launch_event_at: datetime) -> datetime:
    return launch_event_at + LANDMARK_OFFSET


def observation_due_at(
    launch_event_at: datetime,
    horizon_days: int,
) -> datetime:
    if horizon_days not in HORIZON_DAYS:
        raise ValueError(f"Unsupported horizon: {horizon_days}")

    return readiness_landmark(launch_event_at) + timedelta(
        days=horizon_days
    )
