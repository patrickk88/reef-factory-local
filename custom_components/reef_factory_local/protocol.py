"""Local WebSocket protocol of Reef Factory devices (unofficial, reverse engineered).

Endpoint ``ws://<ip>/controler`` with mandatory subprotocol ``arduino``, no
authentication, only ONE client connection per device at a time.

Frame layout, every field NUL-terminated:
    client -> device: <clientid>\\0<topic>\\0<subtopic>\\0<joinid>\\0<data>\\0
    device -> client: <serial>\\0<topic>\\0<subtopic>\\0<joinid>\\0<blob>

Values are only streamed to clients holding a subscription
(``<xx>Connect/join``); one data frame per subscription, so subscribe again
about every 15 seconds.

This module has no Home Assistant dependency so it can be tested on its own.
"""
from __future__ import annotations

import json
import re
import struct
import time
from dataclasses import dataclass

WS_PATH = "/controler"
WS_SUBPROTOCOL = "arduino"
NULL_ID = "0000000000000000"
RESUBSCRIBE_SECONDS = 15
WATCHDOG_SECONDS = 60

DEVICE_LEVEL_KEEPER = "level_keeper"
DEVICE_THERMO = "thermo_control"
DEVICE_FLARE = "reef_flare"
DEVICE_FEEDER = "smart_feeder"  # cloud-only device (no local port), served by the cloud replacement
DEVICE_BASE_PUMP = "base_pump"      # cloud-only, Reef Base pump (return pump)
DEVICE_DOSING_PUMP = "dosing_pump"  # cloud-only, Dosing pump Pro X4

# Cloud channel (what the devices expect from api.reeffactory.com)
CLOUD_HOST = "api.reeffactory.com"
CLOUD_PORT_TLS = 444      # ESP32 devices: TLS without certificate check, path /hardware32
CLOUD_PORT_PLAIN = 442    # ESP8266 devices: plain text, path /hardware, subprotocol "reeffactory"
CLOUD_PATHS = ("/hardware32", "/hardware")
CLOUD_SUBPROTOCOL = "reeffactory"
CLOUD_PING_INTERVAL = 20  # seconds, what the real cloud answers in geReport/login
# devices whose values arrive over the cloud channel only
CLOUD_ONLY = {DEVICE_FEEDER, DEVICE_BASE_PUMP, DEVICE_DOSING_PUMP}

# longest prefix first
_PREFIXES = (
    ("RFRFS", DEVICE_FLARE),
    ("RFRFM", DEVICE_FLARE),
    ("RFRFL", DEVICE_FLARE),
    ("RFLK", DEVICE_LEVEL_KEEPER),
    ("RFTC", DEVICE_THERMO),
    ("RFSF", DEVICE_FEEDER),
    ("RFBP", DEVICE_BASE_PUMP),
    ("RFDQ", DEVICE_DOSING_PUMP),
)
CONNECT_TOPIC = {
    DEVICE_LEVEL_KEEPER: "lkConnect",
    DEVICE_THERMO: "tcConnect",
    DEVICE_FLARE: "rfConnect",
    DEVICE_FEEDER: "sfConnect",
    DEVICE_BASE_PUMP: "bpConnect",
    DEVICE_DOSING_PUMP: "dqConnect",  # yes, dq - the reports and requests use dp
}
MODEL_NAME = {
    DEVICE_LEVEL_KEEPER: "Level keeper",
    DEVICE_THERMO: "Thermo control",
    DEVICE_FLARE: "Reef Flare",
    DEVICE_FEEDER: "Smart feeder",
    DEVICE_BASE_PUMP: "Base pump",
    DEVICE_DOSING_PUMP: "Dosing pump Pro X4",
}
# Smart feeder: feeding modes (sfSet/mode) and units
FEEDER_MODES = {"period": "schedule", "sequence": "interval"}
FEEDER_MODES_REV = {v: k for k, v in FEEDER_MODES.items()}
FEEDER_GRAM_UNITS = 100  # container/dose values are hundredths of a gram
FEEDER_MAX_ROTATIONS = 10
# Dosing pump Pro X4: every volume is ml * 10000 (the app shows 2.00 ml for 20000), four channels
DOSING_ML_UNITS = 10000
DOSING_CHANNELS = 4
# "give me everything" request per cloud device: topic, subtopic, payload
GET_ALL = {
    DEVICE_FEEDER: ("sfGet", "all", None),
    DEVICE_BASE_PUMP: ("bpGet", "all", None),
    DEVICE_DOSING_PUMP: ("dpGet", "all", {"id": 0}),
}
FEEDER_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # bit 0 = Monday (127 = daily)

# Level keeper refill cycle (byte 0 of lkRefresh/settings, same value for lkSet/settings)
LK_CYCLES: dict[int, str] = {
    0: "off",
    1: "every_60_min",
    2: "every_30_min",
    3: "every_10_min",
    4: "constant",
    5: "hysteresis",
}
LK_CYCLES_REV = {v: k for k, v in LK_CYCLES.items()}
# Level keeper state (byte 1 of settings, byte 0 of status)
LK_LEVEL: dict[int, str] = {
    0: "ok",
    1: "refilling",
    2: "manual_refill",
    3: "filling_circuit",
    4: "calibrating",
    5: "water_high",
    6: "water_low",
    7: "temporarily_off",
}
LK_LEVEL_OPTIONS = [*LK_LEVEL.values(), "unknown"]
# calibration reminder period (lkCalibration/notification)
LK_REMINDER = {"1_week": 0, "2_weeks": 1, "1_month": 2, "3_months": 3}
LK_MAX_MINUTES = 60  # limit used by the device UI for max refill time and pause
# Reef Flare: subtopic of rfRefresh = current mode
FLARE_MODES: dict[str, str] = {
    "preciseData": "program",
    "manualData": "manual",
    "offData": "off",
}


def device_type(serial: str) -> str | None:
    """Return the supported device type for a serial number, or None."""
    for prefix, kind in _PREFIXES:
        if serial.startswith(prefix):
            return kind
    return None


def join_id() -> str:
    return f"join_{int(time.time() * 1000)}"


def build_frame(
    topic: str,
    subtopic: str = "",
    data: bytes = b"",
    clientid: str = NULL_ID,
    joinid: str = "",
) -> bytes:
    return b"\x00".join(
        (clientid.encode(), topic.encode(), subtopic.encode(), joinid.encode(), data)
    ) + b"\x00"


def frame_get_config() -> bytes:
    return build_frame("get", "config")


def frame_subscribe(serial: str) -> bytes:
    kind = device_type(serial)
    if kind is None:
        raise ValueError(f"unsupported device {serial!r}")
    return build_frame(
        CONNECT_TOPIC[kind], "join", serial.encode() + b"\x00", serial, join_id()
    )


def frame_lk_set_cycle(serial: str, cycle: str) -> bytes:
    if cycle not in LK_CYCLES_REV:
        raise ValueError(f"unknown cycle {cycle!r}")
    return build_frame(
        "lkSet", "settings", bytes([LK_CYCLES_REV[cycle]]), serial, join_id()
    )


def _u32(value: int) -> bytes:
    return struct.pack(">I", max(0, int(value)) & 0xFFFFFFFF)


def _lk(serial: str, sub: str, data: bytes = b"", topic: str = "lkSet") -> bytes:
    return build_frame(topic, sub, data, serial, join_id())


def frame_lk_set_light(serial: str, on: bool) -> bytes:
    return _lk(serial, "light", bytes([1 if on else 0]))


def frame_lk_set_max_refill_time(serial: str, minutes: int) -> bytes:
    """0 switches the limit off; the device UI allows 0..60 minutes."""
    return _lk(serial, "maxRefillTime", _u32(min(max(minutes, 0), LK_MAX_MINUTES) * 60))


def frame_lk_temporary_off(serial: str, minutes: int) -> bytes:
    """Pause automatic refill for 0..60 minutes; 0 ends the pause."""
    return _lk(serial, "temporaryOff", _u32(min(max(minutes, 0), LK_MAX_MINUTES) * 60))


def frame_lk_manual_refill_start(serial: str, ml: int) -> bytes:
    return _lk(serial, "start", _u32(ml), topic="lkManualRefill")


def frame_lk_manual_refill_stop(serial: str) -> bytes:
    return _lk(serial, "stop", topic="lkManualRefill")


def frame_lk_calibration_time(serial: str, seconds: int) -> bytes:
    return _lk(serial, "time", bytes([min(max(int(seconds), 0), 255)]), topic="lkCalibration")


def frame_lk_calibration_start(serial: str) -> bytes:
    return _lk(serial, "start", topic="lkCalibration")


def frame_lk_calibration_stop(serial: str) -> bytes:
    return _lk(serial, "stop", topic="lkCalibration")


def frame_lk_calibration_value(serial: str, ml: int) -> bytes:
    return _lk(serial, "value", _u32(ml), topic="lkCalibration")


def frame_lk_calibration_reminder(serial: str, period: str) -> bytes:
    return _lk(serial, "notification", bytes([LK_REMINDER[period]]), topic="lkCalibration")


def frame_lk_circuit_start(serial: str) -> bytes:
    return _lk(serial, "circuitStart", topic="lkCalibration")


def frame_lk_circuit_stop(serial: str) -> bytes:
    return _lk(serial, "circuitStop", topic="lkCalibration")


def frame_set_time(serial: str, when, h24: bool = True) -> bytes:
    """Device clock: year (u16), month, day, hour, minute, second, 24h flag."""
    data = struct.pack(">H", when.year) + bytes(
        [when.month, when.day, when.hour, when.minute, when.second, 1 if h24 else 0]
    )
    return build_frame("set", "time", data, serial, join_id())


TC_SCALE = 1000  # thermo temperatures are int32 * 1000


def frame_tc_set_settings(
    serial: str, range_low: float, range_high: float, alarm_low: float, alarm_high: float,
    fahrenheit: bool = False,
) -> bytes:
    """All four thresholds are always sent together (17 bytes, like the device UI)."""
    data = b"".join(
        struct.pack(">i", round(v * TC_SCALE)) for v in (range_low, range_high, alarm_low, alarm_high)
    ) + bytes([1 if fahrenheit else 0])
    return build_frame("tcSet", "settings", data, serial, join_id())


def frame_tc_light(serial: str, on: bool) -> bytes:
    return build_frame("tcLight", "on" if on else "off", b"", serial, join_id())


def frame_tc_sound(serial: str, on: bool) -> bytes:
    return build_frame("tcSound", "on" if on else "off", b"", serial, join_id())


FLARE_CHANNELS = 7
FLARE_MODE_CMD = {"program": "precise", "manual": "manual", "off": "off"}


def frame_rf_mode(serial: str, mode: str) -> bytes:
    """Switch Reef Flare mode: program / manual / off (rfMode/<x>, no data)."""
    return build_frame("rfMode", FLARE_MODE_CMD[mode], b"", serial, join_id())


def frame_rf_select_program(serial: str, index: int) -> bytes:
    return build_frame("rfPrecise", "select", bytes([index & 0xFF]), serial, join_id())


def _pct(value) -> int:
    return min(max(int(round(value)), 0), 100)


def frame_rf_precise_update(serial: str, index: int, time_raw: int, points: list[dict], intensity: int) -> bytes:
    """Rewrite one stored program (layout of the device UI's save()): index, u32, count, points, intensity."""
    body = bytes([index & 0xFF]) + struct.pack(">I", time_raw & 0xFFFFFFFF) + bytes([len(points)])
    for point in points:
        body += struct.pack(">H", point["minute"]) + bytes(_pct(v) for v in point["levels"][:FLARE_CHANNELS])
    return build_frame("rfPrecise", "update", body + bytes([_pct(intensity)]), serial, join_id())


def frame_rf_manual_update(serial: str, presets: list[dict]) -> bytes:
    """Whole manual preset list: count, per preset name (UTF-16BE, 0000), active, 7 levels; then intensities."""
    body = bytes([len(presets)])
    for preset in presets:
        body += preset["name"][:16].encode("utf-16-be") + b"\x00\x00" + bytes([1 if preset["active"] else 0])
        body += bytes(_pct(v) for v in preset["levels"][:FLARE_CHANNELS])
    body += bytes(_pct(p.get("intensity", 100)) for p in presets)
    return build_frame("rfManual", "update", body, serial, join_id())


def frame_rf_manual_time(serial: str, seconds: int | None) -> bytes:
    """Manual mode duration in seconds (device UI: 1 min .. 6 h); None = always (FFFF)."""
    value = 0xFFFF if seconds is None else min(max(int(seconds), 1), 0xFFFE)
    return build_frame("rfManual", "time", struct.pack(">H", value), serial, join_id())


def frame_rf_acclimation(serial: str, days: int = 0, start: int = 0, end: int = 0) -> bytes:
    """Start acclimation (days 2..30, start/end intensity %); all zero stops it."""
    data = bytes([0, 0, 0]) if days == 0 else bytes([min(max(int(days), 2), 30), _pct(start), _pct(end)])
    return build_frame("rfPrecise", "acclimation", data, serial, join_id())


def frame_rf_program_name(serial: str, index: int, name: str) -> bytes:
    """Rename a stored program: index, name (UTF-16BE, max 16 characters), 0000."""
    body = bytes([index & 0xFF]) + name[:16].encode("utf-16-be") + b"\x00\x00"
    return build_frame("rfPrecise", "name", body, serial, join_id())


def frame_rf_preview(serial: str, start: bool) -> bytes:
    """Accelerated preview of the active program (rfPreview/start|stop, no data)."""
    return build_frame("rfPreview", "start" if start else "stop", b"", serial, join_id())


FLARE_MAX_POINTS = 31  # device UI: fewer than 32 points per program
FLARE_NAME_MAX = 16


def parse_hhmm(value) -> int:
    """'HH:MM' (also 'HH:MM:SS', '24:00') -> minute of the day (0..1440)."""
    if isinstance(value, int):
        minute = value
    else:
        parts = [int(x) for x in str(value).strip().split(":")]
        if len(parts) < 2 or not 0 <= parts[1] < 60:
            raise ValueError(f"invalid time {value!r}")
        minute = parts[0] * 60 + parts[1]
    if not 0 <= minute <= 1440:
        raise ValueError(f"invalid time {value!r}")
    return minute


def normalize_flare_points(points: list) -> list[dict]:
    """Validate a program as the device UI does: first point 00:00, last 24:00,
    strictly increasing, 7 channel levels 0..100 %, at most 31 points."""
    out = []
    for point in points:
        levels = [int(round(float(v))) for v in point["levels"]]
        if len(levels) != FLARE_CHANNELS or not all(0 <= v <= 100 for v in levels):
            raise ValueError(f"each point needs {FLARE_CHANNELS} levels between 0 and 100")
        out.append({"minute": parse_hhmm(point.get("minute", point.get("time"))), "levels": levels})
    if not 2 <= len(out) <= FLARE_MAX_POINTS:
        raise ValueError(f"a program needs 2 to {FLARE_MAX_POINTS} points")
    if out[0]["minute"] != 0 or out[-1]["minute"] != 1440:
        raise ValueError("the first point must be 00:00 and the last 24:00")
    if any(b["minute"] <= a["minute"] for a, b in zip(out, out[1:])):
        raise ValueError("point times must be strictly increasing")
    return out


def frame_get_user(serial: str) -> bytes:
    """Only answered when sent with the device serial and a join id (checked 29.10.2026)."""
    return build_frame("get", "user", b"", serial, join_id())


# ---------------------------------------------------------------------------
# Cloud channel: same NUL framing, but the payload is JSON (observed 03.11.2026
# with a Smart feeder, firmware 1.1.6). The device sends <serial>\0geConnect\0login\0\0{json}\0,
# the cloud answers geReport/login and geSet/time, then clients subscribe with
# <xx>Connect/join and ask <xx>Get/all; the device reports <xx>Report/all after
# every change.
# ---------------------------------------------------------------------------

def frame_json(serial: str, topic: str, subtopic: str, obj: dict | None = None, joinid: str = "") -> bytes:
    data = b"" if obj is None else json.dumps(obj, separators=(",", ":")).encode()
    return build_frame(topic, subtopic, data, serial, joinid)


def parse_json(frame: "Frame") -> dict | None:
    """JSON payload of a cloud frame (None when empty or not JSON)."""
    raw = frame.blob.rstrip(b"\x00")
    if not raw:
        return None
    try:
        obj = json.loads(raw.decode())
    except (UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def parse_login(frame: "Frame") -> dict | None:
    """geConnect/login from the device: key, token, email, version. Secrets are kept out."""
    if frame.topic != "geConnect" or frame.subtopic != "login":
        return None
    obj = parse_json(frame) or {}
    return {"serial": frame.serial, "firmware": obj.get("version"), "has_token": bool(obj.get("token"))}


def frame_login_ok(serial: str) -> bytes:
    return frame_json(serial, "geReport", "login", {"status": "success", "pingInterval": CLOUD_PING_INTERVAL})


def frame_cloud_time(serial: str, when) -> bytes:
    """geSet/time as the cloud sends it: two-digit year, weekday 1 = Monday."""
    return frame_json(serial, "geSet", "time", {
        "year": when.year % 100, "month": when.month, "day": when.day, "weekday": when.isoweekday(),
        "hour": when.hour, "minutes": when.minute, "seconds": when.second,
    })


def cloud_join_id() -> str:
    return str(int(time.time() * 1000))


def frame_cloud_subscribe(serial: str, joinid: str) -> bytes:
    kind = device_type(serial)
    if kind is None:
        raise ValueError(f"unsupported device {serial!r}")
    return build_frame(CONNECT_TOPIC[kind], "join", serial.encode(), serial, joinid)


def frame_cloud_get_all(serial: str, joinid: str) -> bytes:
    kind = device_type(serial)
    if kind not in GET_ALL:
        raise ValueError(f"unsupported device {serial!r}")
    topic, subtopic, obj = GET_ALL[kind]
    return frame_json(serial, topic, subtopic, obj, joinid)


def frame_cloud_get_wifi(serial: str, joinid: str) -> bytes:
    """geGet/wifiStrength - answered with geReport/wifiStrength {"value": <dBm>} (all cloud devices)."""
    return build_frame("geGet", "wifiStrength", b"", serial, joinid)


def _decode_wifi(frame: "Frame") -> dict | None:
    if frame.topic == "geReport" and frame.subtopic == "wifiStrength":
        obj = parse_json(frame)
        return None if obj is None else {"wifi_rssi": obj.get("value")}
    return None


def _on_off(value) -> bool | None:
    if value is None:
        return None
    return value in ("on", "enabled", 1, True, "1")


# --- Base pump ----------------------------------------------------------------

def decode_base_pump(frame: "Frame") -> dict | None:
    """bpReport/all of the Base pump (plus the generic wifi report)."""
    if (wifi := _decode_wifi(frame)) is not None:
        return wifi
    obj = parse_json(frame)
    if obj is None:
        return None
    if frame.topic == "bpReport" and frame.subtopic == "feed":  # feed mode countdown, once a second
        return {"feed_remaining_s": obj.get("time"), "mode": "feedMode"}
    if frame.topic == "bpLog" and frame.subtopic == "mode":
        mode = obj.get("mode")
        out = {"mode": mode}
        if mode != "feedMode":
            out["feed_remaining_s"] = 0
        return out
    if frame.topic != "bpReport" or frame.subtopic != "all":
        return None
    return {
        "mode": obj.get("mode"),
        "alert": obj.get("alert"),
        "alert_active": obj.get("alert") not in (None, "noErrors"),
        "speed": obj.get("speed"),
        "feed_mode_time": obj.get("feedModeTime"),
        "feed_speed": obj.get("feedSpeed"),
        "display": _on_off(obj.get("display")),
        "backlight": _on_off(obj.get("backlight")),
    }


def frame_bp_set_settings(serial: str, speed: int, feed_mode_time: int, feed_speed: int,
                          display: bool, backlight: bool, joinid: str = "") -> bytes:
    """bpSet/settings - the app always sends all five values together."""
    return frame_json(serial, "bpSet", "settings", {
        "speed": int(speed), "feedModeTime": int(feed_mode_time), "feedSpeed": int(feed_speed),
        "display": "on" if display else "off", "backlight": "on" if backlight else "off",
    }, joinid)


BASE_PUMP_MODES = ("auto", "feedMode")


def frame_bp_set_mode(serial: str, mode: str, joinid: str = "") -> bytes:
    """bpSet/mode - "feedMode" starts the feed pause (pump at feedSpeed for feedModeTime), "auto" ends it."""
    if mode not in BASE_PUMP_MODES:
        raise ValueError(f"unknown base pump mode {mode!r}")
    return frame_json(serial, "bpSet", "mode", {"mode": mode}, joinid)


# --- Dosing pump Pro X4 ---------------------------------------------------------

def _ml(value) -> float | None:
    return None if value is None else round(value / DOSING_ML_UNITS, 4)


def _dp_units(ml) -> int:
    return max(0, int(round(float(ml) * DOSING_ML_UNITS)))


def _minute_to_hhmm(minute: int) -> str:
    return f"{int(minute) // 60:02d}:{int(minute) % 60:02d}"


def decode_dosing_pump(frame: "Frame") -> dict | None:
    """dpReport/all of the Dosing pump Pro X4 - one frame per channel, keys prefixed ch<n>_."""
    if (wifi := _decode_wifi(frame)) is not None:
        return wifi
    obj = parse_json(frame)
    if obj is None:
        return None
    if frame.topic == "dpLog" and frame.subtopic == "dose":  # a dose just finished
        cid = obj.get("id")
        if isinstance(cid, int):
            return {f"ch{cid}_dose_event_ml": _ml(obj.get("value"))}
        return None
    if frame.topic != "dpReport" or frame.subtopic != "all":
        return None
    cid = obj.get("id")
    if not isinstance(cid, int) or not 1 <= cid <= DOSING_CHANNELS:
        return None
    st = obj.get("settings") or {}
    cont = obj.get("container") or {}
    cal = obj.get("calibration") or {}
    hist = (obj.get("history") or {}).get("history") or []
    nxt = st.get("nextDose") or {}
    p = f"ch{cid}_"
    schedule = []
    for e in st.get("schedule") or []:
        if isinstance(e, dict) and "t" in e:
            schedule.append({"time": _minute_to_hhmm(e["t"]), "days": _days_from_mask(int(e.get("d", 127))),
                             "ml": _ml(e.get("v")), "direction": e.get("dir")})
    cd = cal.get("calibDate") or {}
    cal_date = None
    if cd.get("year"):
        cal_date = (2000 + int(cd["year"]) if int(cd["year"]) < 100 else int(cd["year"]), int(cd.get("month") or 1), int(cd.get("day") or 1))
    last = hist[0] if hist else {}
    history = [{"date": h.get("d"), "time": h.get("t"), "auto_ml": _ml(h.get("ad")), "manual_ml": _ml(h.get("md"))}
               for h in hist[:10] if isinstance(h, dict)]
    out = {
        p + "present": True,
        p + "name": st.get("name") or "",
        p + "mode": st.get("mode"),
        p + "off_duration": st.get("offDuration"),
        p + "schedule": schedule,
        p + "next_dose": f"{nxt['date']} {nxt['time']}" if nxt.get("date") and nxt.get("time") else None,
        p + "next_dose_ml": _ml(nxt.get("value")),
        p + "container_status": cont.get("status"),
        p + "container_ml": _ml(cont.get("value")),
        p + "container_size_ml": _ml(cont.get("capacity")),
        p + "days_to_replace": cont.get("daysToReplace"),
        p + "reminder_days": cont.get("reminderDays"),
        p + "daily_target_ml": _ml((cont.get("auto") or {}).get("targetDose")),
        p + "dosed_today_ml": _ml((cont.get("auto") or {}).get("currentDose")),
        p + "manual_target_ml": _ml((cont.get("manual") or {}).get("targetDose")),
        p + "manual_done_ml": _ml((cont.get("manual") or {}).get("currentDose")),
        p + "pump_min_ml_min": _ml((cont.get("pump") or {}).get("minMlPerMin")),
        p + "pump_max_ml_min": _ml((cont.get("pump") or {}).get("maxMlPerMin")),
        p + "calibration_state": cal.get("state"),
        p + "calibration_coeff": cal.get("calibCoeff"),
        p + "calibration_date": cal_date,
        p + "calibration_reminder_days": cal.get("reminderDays"),
        p + "days_to_next_calibration": cal.get("daysToNextCalib"),
        p + "last_dose": f"{last['d']} {last['t']}" if last.get("d") and last.get("t") else None,
        p + "last_dose_ml": _ml((last.get("ad") or 0) + (last.get("md") or 0)) if last else None,
        p + "last_dose_type": (None if not last else ("manual" if last.get("md") else "auto")),
        p + "history": history,
    }
    return out


# --- Smart feeder -----------------------------------------------------------

def _days_from_mask(mask: int) -> list[str]:
    return [d for i, d in enumerate(FEEDER_DAYS) if mask & (1 << i)]


def days_to_mask(days) -> int:
    if isinstance(days, int):
        return days & 0x7F
    mask = 0
    for day in days:
        mask |= 1 << FEEDER_DAYS.index(str(day).lower()[:3])
    return mask


def _grams(value) -> float | None:
    return None if value is None else round(value / FEEDER_GRAM_UNITS, 2)


def decode_feeder(frame: "Frame") -> dict | None:
    """sfReport/all and sfLog/* of the Smart feeder."""
    if (wifi := _decode_wifi(frame)) is not None:
        return wifi
    if frame.topic == "sfReport" and frame.subtopic == "all":
        obj = parse_json(frame)
        if obj is None:
            return None
        cont = obj.get("container") or {}
        seq = obj.get("sequence") or {}
        nxt = obj.get("nextFeeding") or {}
        hist = obj.get("history") or []
        last = hist[0] if hist else {}
        return {
            "mode": FEEDER_MODES.get(obj.get("mode"), obj.get("mode")),
            "schedule": [{"time": f"{p['time'] // 60:02d}:{p['time'] % 60:02d}", "minute": p["time"],
                          "rotations": p.get("rotations", 1), "days": _days_from_mask(p.get("days", 127)),
                          "days_mask": p.get("days", 127)} for p in obj.get("periods") or []],
            "interval_minutes": seq.get("frequency"),
            "interval_rotations": seq.get("rotations"),
            "next_feeding": f"{nxt.get('date')} {nxt.get('time')}" if nxt.get("date") else None,
            "next_feeding_g": _grams(nxt.get("doseValue")),
            "container_g": _grams(cont.get("value")),
            "container_size_g": _grams(cont.get("size")),
            "single_dose_g": _grams(cont.get("singleDose")),
            "days_to_end": cont.get("daysToEnd"),
            "reminder_days": cont.get("reminderDays"),
            "last_feeding": f"{last.get('date')} {last.get('time')}" if last else None,
            "last_feeding_type": last.get("doseType"),
            "last_feeding_g": _grams(last.get("doseValue")),
            "history": hist[:10],
            "daily_dose_g": _grams(obj.get("dailyDose")),
            "led": obj.get("ledStatus") == "enabled",
            "feeding_button": obj.get("feedingButton") == "enabled",
        }
    if frame.topic == "sfLog":
        obj = parse_json(frame) or {}
        if frame.subtopic == "container":
            cont = obj.get("container") or {}
            return {"container_alert": cont.get("alert"), "container_empty": cont.get("alert") == "empty"}
        if frame.subtopic == "dose":
            dose = obj.get("dose") or {}
            return {"last_dose_event": {"type": dose.get("type"), "grams": _grams(dose.get("value"))},
                    "container_empty": False}
    return None


def frame_sf_feed(serial: str, rotations: int = 1, joinid: str = "") -> bytes:
    return frame_json(serial, "sfExecute", "manual",
                      {"rotations": min(max(int(rotations), 1), FEEDER_MAX_ROTATIONS)}, joinid)


def frame_sf_set_mode(serial: str, mode: str, joinid: str = "") -> bytes:
    return frame_json(serial, "sfSet", "mode", {"mode": FEEDER_MODES_REV.get(mode, mode)}, joinid)


def frame_sf_set_settings(serial: str, settings: dict, joinid: str = "") -> bytes:
    """Partial settings as the app sends them: periods / sequence / ledStatus+feedingButton / reminderDays."""
    return frame_json(serial, "sfSet", "settings", settings, joinid)


def frame_sf_set_schedule(serial: str, entries: list[dict], joinid: str = "") -> bytes:
    periods = []
    for e in entries:
        periods.append({"time": parse_hhmm(e.get("minute", e.get("time"))),
                        "rotations": min(max(int(e.get("rotations", 1)), 1), FEEDER_MAX_ROTATIONS),
                        "days": days_to_mask(e.get("days", 127))})
    return frame_sf_set_settings(serial, {"periods": periods}, joinid)


def frame_sf_set_interval(serial: str, minutes: int, rotations: int, joinid: str = "") -> bytes:
    return frame_sf_set_settings(serial, {"sequence": {"frequency": int(minutes), "rotations": int(rotations)}}, joinid)


def frame_sf_set_flags(serial: str, led: bool, button: bool, joinid: str = "") -> bytes:
    return frame_sf_set_settings(serial, {"ledStatus": "enabled" if led else "disabled",
                                          "feedingButton": "enabled" if button else "disabled"}, joinid)


def frame_sf_set_reminder(serial: str, days: int, joinid: str = "") -> bytes:
    return frame_sf_set_settings(serial, {"reminderDays": int(days)}, joinid)


def frame_sf_set_container(serial: str, value_g: float, size_g: float, single_dose_g: float, joinid: str = "") -> bytes:
    g = lambda v: int(round(float(v) * FEEDER_GRAM_UNITS))
    return frame_json(serial, "sfSet", "container",
                      {"value": g(value_g), "size": g(size_g), "singleDose": g(single_dose_g)}, joinid)


@dataclass(frozen=True)
class Frame:
    serial: str
    topic: str
    subtopic: str
    joinid: str
    blob: bytes


def parse_frame(raw: bytes) -> Frame | None:
    parts = raw.split(b"\x00", 4)
    if len(parts) < 5:
        return None
    serial, topic, subtopic, joinid = (p.decode("latin1") for p in parts[:4])
    return Frame(serial, topic, subtopic, joinid, parts[4])


def _be(blob: bytes, start: int, size: int) -> int | None:
    if len(blob) < start + size:
        return None
    return int.from_bytes(blob[start:start + size], "big")


def _seconds(blob: bytes, start: int) -> int | None:
    """Signed 32-bit seconds as the device UI reads them; <= 0 means 'not set'."""
    raw = _be(blob, start, 4)
    if raw is None:
        return None
    value = raw - (1 << 32) if raw & 0x80000000 else raw
    return max(value, 0)


def decode_level_keeper(frame: Frame) -> dict | None:
    if frame.topic != "lkRefresh":
        return None
    blob, sub = frame.blob, frame.subtopic
    if sub == "settings":
        if len(blob) < 15:
            return None
        data: dict = {
            "cycle": LK_CYCLES.get(blob[0]),
            "level": LK_LEVEL.get(blob[1], "unknown"),
            "level_raw": blob[1],
            "calibration_needed": blob[10] != 0,
            "refilled_today_ml": _be(blob, 11, 4),
        }
        year = _be(blob, 8, 2)
        if year:
            data["calibration_date"] = (year, (blob[7] - 1) % 12 + 1, blob[6])
        if len(blob) >= 25:
            data["calibration_remaining_s"] = blob[15]
            data["circuit_remaining_s"] = blob[16]
            data["manual_refill_done_ml"] = _be(blob, 17, 4)
            data["manual_refill_target_ml"] = _be(blob, 21, 4)
        if len(blob) >= 33:  # firmware >= 0.6.4
            data["max_refill_time_s"] = _seconds(blob, 25)
            data["temporary_off_s"] = _seconds(blob, 29)
        if len(blob) >= 34 and blob[33] in (0, 1):  # firmware >= 0.6.5
            data["light"] = blob[33] == 1
        return data
    if sub == "status" and len(blob) >= 5:
        data = {
            "level": LK_LEVEL.get(blob[0], "unknown"),
            "level_raw": blob[0],
            "refilled_today_ml": _be(blob, 1, 4),
        }
        if len(blob) >= 9:
            data["refill_time_s"] = _be(blob, 5, 4)
        return data
    if sub == "alert" and blob:
        data = {"alert_code": blob[0]}
        if blob[0] in (0, 1):
            data["calibration_needed"] = blob[0] == 1
        return data
    if sub == "temporary" and len(blob) >= 4:
        return {"temporary_off_s": _seconds(blob, 0)}
    if sub == "manualRefill" and len(blob) >= 8:
        return {"manual_refill_done_ml": _be(blob, 0, 4), "manual_refill_target_ml": _be(blob, 4, 4)}
    if sub == "calibration" and blob:
        return {"calibration_remaining_s": blob[0]}
    if sub == "circuit" and blob:
        return {"circuit_remaining_s": blob[0]}
    if sub in ("manualRefillStop", "calibrationStop", "circuitStop"):
        return {"last_event": sub}
    return None


def parse_user(frame: Frame) -> dict | None:
    """Answer to get/user (topic status, subtopic user). The account name is dropped on purpose."""
    if frame.topic != "status" or frame.subtopic != "user":
        return None
    blob = frame.blob
    _name, sep, rest = blob.partition(b"\x00")
    if not sep or len(rest) < 3:
        return None
    return {"wifi_connected": rest[1] == 3 and rest[0] != 0, "cloud_connected": rest[2] == 2}


def _tc_temp(blob: bytes, start: int) -> float | None:
    raw = blob[start:start + 4]
    if len(raw) < 4 or raw == b"\xff\xff\xff\xff":
        return None
    return struct.unpack(">i", raw)[0] / TC_SCALE


def decode_thermo(frame: Frame) -> dict | None:
    """tcRefresh/settings, layout from the device UI (checked 29.10.2026)."""
    if frame.topic != "tcRefresh" or frame.subtopic != "settings" or len(frame.blob) < 4:
        return None
    blob = frame.blob
    data: dict = {"temperature": _tc_temp(blob, 0)}
    if len(blob) >= 23:
        data.update({
            "fahrenheit": blob[4] != 0,
            "alarm_low": _tc_temp(blob, 5),
            "range_low": _tc_temp(blob, 9),
            "heating": blob[13] != 0,
            "alarm_high": _tc_temp(blob, 14),
            "range_high": _tc_temp(blob, 18),
            "cooling": blob[22] != 0,
        })
        data["state"] = "heating" if data["heating"] else ("cooling" if data["cooling"] else "idle")
    if len(blob) >= 25:
        flags = blob[24]
        data["sound"] = (flags & 0x0F) != 0
        light = flags & 0xF0
        data["light"] = True if light == 0x80 else (False if light == 0x90 else None)
    return data


def _utf16_name(blob: bytes, pos: int) -> tuple[str, int] | None:
    """UTF-16BE characters up to 0x0000. Returns (name, position after terminator)."""
    out = []
    while pos + 1 < len(blob):
        code = (blob[pos] << 8) | blob[pos + 1]
        pos += 2
        if code == 0:
            return "".join(out), pos
        out.append(chr(code))
    return None


def _flare_list(blob: bytes, pos: int, levels: bool) -> tuple[list[dict], int] | None:
    """Program (preciseData) or preset (manualData) list starting with a count byte."""
    if pos >= len(blob):
        return None
    count = blob[pos]
    pos += 1
    if not 0 < count <= 8:
        return None
    items = []
    for _ in range(count):
        res = _utf16_name(blob, pos)
        if res is None or res[1] >= len(blob):
            return None
        name, pos = res
        item = {"name": name, "active": blob[pos] != 0}
        pos += 1
        if levels:
            if pos + FLARE_CHANNELS > len(blob):
                return None
            item["levels"] = list(blob[pos:pos + FLARE_CHANNELS])
            pos += FLARE_CHANNELS
        items.append(item)
    return items, pos


def _active(items: list[dict]) -> int:
    return next((i for i, it in enumerate(items) if it["active"]), 0)


def _flare_program_data(blob: bytes, pos: int) -> dict:
    """Points, intensity and acclimation of the active program (layout from the device UI)."""
    out: dict = {}
    if pos + 5 > len(blob):
        return out
    out["time_raw"] = int.from_bytes(blob[pos:pos + 4], "big")
    count = blob[pos + 4]
    pos += 5
    points = []
    for _ in range(count):
        if pos + 2 + FLARE_CHANNELS > len(blob):
            return out
        minute = (blob[pos] << 8) | blob[pos + 1]
        points.append({"time": f"{minute // 60:02d}:{minute % 60:02d}", "minute": minute,
                       "levels": list(blob[pos + 2:pos + 2 + FLARE_CHANNELS])})
        pos += 2 + FLARE_CHANNELS
    out["points"] = points
    if pos < len(blob):  # firmware > 0.6.9
        out["intensity"] = blob[pos]
        pos += 1
    if pos + 5 <= len(blob):  # firmware > 0.7.0
        day, days, start, end = blob[pos], blob[pos + 1], blob[pos + 2], blob[pos + 3]
        out["acclimation"] = {"day": day, "days": days, "start": start, "end": end} if days else None
    return out


def decode_flare(frame: Frame) -> dict | None:
    if frame.topic != "rfRefresh":
        return None
    blob, sub = frame.blob, frame.subtopic
    if sub == "dashboardData":
        # sent in every refresh cycle next to the mode frame, so it says nothing about the mode
        # (observed: blob[0] == 1, blob[1] == housing temperature)
        return {"temperature": blob[1]} if len(blob) > 1 else None
    data: dict = {}
    if sub in FLARE_MODES:
        data["mode"] = FLARE_MODES[sub]
    if sub == "temp" and blob:
        return {"temperature": blob[0]}
    if blob:
        data["temperature"] = blob[0]
    if sub == "preciseData" and len(blob) >= 5:
        list_len = (blob[2] << 8) | blob[3]
        res = _flare_list(blob, 4, levels=False)
        if res:
            programs, _ = res
            idx = _active(programs)
            data["programs"] = [p["name"] for p in programs]
            data["program_index"] = idx
            data["program"] = programs[idx]["name"] or None
        prog = _flare_program_data(blob, 4 + list_len)
        data["intensity"] = prog.get("intensity")
        data["points"] = prog.get("points")
        data["acclimation"] = prog.get("acclimation")
        data["program_time_raw"] = prog.get("time_raw")
    elif sub == "manualData" and len(blob) >= 5:
        seconds = (blob[2] << 8) | blob[3]
        data["manual_time_s"] = None if seconds == 0xFFFF else seconds  # None = always
        res = _flare_list(blob, 4, levels=True)
        if res:
            presets, pos = res
            idx = _active(presets)
            if pos + len(presets) <= len(blob):  # firmware > 0.6.9: intensity per preset
                for i, preset in enumerate(presets):
                    preset["intensity"] = blob[pos + i]
            data["presets"] = [p["name"] for p in presets]
            data["manual_presets"] = presets
            data["program"] = presets[idx]["name"] or None
            data["levels"] = presets[idx]["levels"]
            data["intensity"] = presets[idx].get("intensity")
    return data or None


_FW_RE = re.compile(rb"(\d+\.\d+\.\d+)")


def parse_config(frame: Frame) -> dict | None:
    """Answer to get/config (topic refresh/config): serial, firmware, device clock.

    Observed blob: <serial>\0 03 00 "1.0.0" <year u16 BE> <month> <day> <hour> <minute> ...
    """
    if frame.topic != "refresh" or frame.subtopic != "config":
        return None
    blob = frame.blob
    serial_raw, _, rest = blob.partition(b"\x00")
    serial = serial_raw.decode("latin1") or frame.serial
    info: dict = {"serial": serial, "device_type": device_type(serial)}
    m = _FW_RE.search(rest)
    if m:
        info["firmware"] = m.group(1).decode()
        tail = rest[m.end():]
        if len(tail) >= 6:
            year = struct.unpack(">H", tail[0:2])[0]
            info["clock"] = f"{year:04d}-{tail[2]:02d}-{tail[3]:02d} {tail[4]:02d}:{tail[5]:02d}"
        if len(tail) >= 8:
            info["clock_24h"] = tail[7] != 0
    return info


def frame_dp_manual_dose(serial: str, channel: int, ml: float, joinid: str = "") -> bytes:
    """dpManual/set refillStart - dose <ml> now on channel 1-4 (the app's manual dose)."""
    return frame_json(serial, "dpManual", "set", {
        "id": int(channel), "command": "refillStart",
        "refill": {"value": _dp_units(ml), "dir": "f", "days": 0, "delay": 0},
    }, joinid)


def frame_dp_set_schedule(serial: str, channel: int, entries: list[dict], joinid: str = "") -> bytes:
    """dpSettings/set - replace the schedule of one channel: [{time: 'HH:MM', ml: x, days: [...] | mask}]."""
    schedule = []
    for e in entries:
        minute = parse_hhmm(e.get("minute", e.get("time")))
        if not 0 <= minute < 1440:
            raise ValueError(f"time out of range: {e.get('time')!r}")
        schedule.append({"t": minute, "d": days_to_mask(e.get("days", 127)), "v": _dp_units(e["ml"]), "dir": "f"})
    schedule.sort(key=lambda x: x["t"])
    return frame_json(serial, "dpSettings", "set", {"settings": [{"id": int(channel), "schedule": schedule}]}, joinid)


def frame_dp_calibration(serial: str, channel: int, start: bool, seconds: int = 30, joinid: str = "") -> bytes:
    """dpCalibration/set startCalib (pump runs <seconds>) / cancelCalib. Storing the measured amount is not captured yet."""
    obj = {"id": int(channel), "command": "startCalib" if start else "cancelCalib"}
    if start:
        obj["time"] = int(seconds)
    return frame_json(serial, "dpCalibration", "set", obj, joinid)


_DECODERS = {
    DEVICE_FEEDER: decode_feeder,
    DEVICE_BASE_PUMP: decode_base_pump,
    DEVICE_DOSING_PUMP: decode_dosing_pump,
    DEVICE_LEVEL_KEEPER: decode_level_keeper,
    DEVICE_THERMO: decode_thermo,
    DEVICE_FLARE: decode_flare,
}


def decode(kind: str, frame: Frame) -> dict | None:
    return _DECODERS[kind](frame)
