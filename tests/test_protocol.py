"""Offline tests for protocol.py using real frames captured on 29.10.2026
(device -> poller on the LAN, and device -> cloud for the Flare dashboard frame)."""
import importlib.util, pathlib, sys

P = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "reef_factory_local" / "protocol.py"
spec = importlib.util.spec_from_file_location("protocol", P)
pr = importlib.util.module_from_spec(spec); sys.modules["protocol"] = pr; spec.loader.exec_module(pr)

LK_SETTINGS = bytes.fromhex(
    "52464c4b303132333034323030303137006c6b526566726573680073657474696e6773006a6f696e5f31373933323338303437313539"
    "0004050000000a010107e3010000005a00000000000000000000ffffffff000000000100000180")
LK_ALERT = bytes.fromhex("52464c4b303132333034323030303137006c6b5265667265736800616c657274000003")
TC_SETTINGS = bytes.fromhex(
    "52465443303132333130323430303135007463526566726573680073657474696e6773006a6f696e5f31373933323338303938303434"
    "0000005fb40000005b6800005eec000000684c0000646400008000000000")
FLARE_CONFIG = bytes.fromhex(
    "52465246533632343033323230303338007265667265736800636f6e666967000052465246533632343033323230303338000300312e302e3007ea0a1d022b010101")
FLARE_DASHBOARD = b"RFRFS62310180008\x00rfRefresh\x00dashboardData\x00\x00\x01\x1f\x01" + b"\x00" * 10
# real frames from Flare .32 (serial RFRFS62403220038), 29.10.2026 02:58
FLARE_PRECISE = bytes.fromhex(
    "5246524653363234303332323030333800726652656672657368007072656369736544617461006a6f696e5f31373933323339303733343039"
    "001f0100790800470065006d0069007300630068007400650020004b006f00720061003700350000010047007000740031000000004700700074"
    "003200200073007400610062006c00650020003500300025000000004700700074003300200036003000250020007a00690065006c0000000000"
    "000000000000000000000000000008000000000000000000026b0000000000000002b86464646432325004384748646432324604bc3d42436"
    "42a240c05190000020000000005450000000000000005a0000000000000001e0000000000")
FLARE_DASHBOARD_REAL = bytes.fromhex(
    "52465246533632343033323230303338007266526566726573680064617368626f617264446174610000011e0100000000000000000000")

def test_device_type():
    assert pr.device_type("RFLK012304200017") == pr.DEVICE_LEVEL_KEEPER
    assert pr.device_type("RFTC012310240015") == pr.DEVICE_THERMO
    assert pr.device_type("RFRFS62310180008") == pr.DEVICE_FLARE
    assert pr.device_type("RFBP052309210012") is None  # base pump: cloud only

def test_build_frames():
    assert pr.frame_get_config() == b"0000000000000000\x00get\x00config\x00\x00\x00"
    f = pr.frame_subscribe("RFLK012304200017").split(b"\x00")
    assert f[0] == b"RFLK012304200017" and f[1] == b"lkConnect" and f[2] == b"join"
    assert f[3].startswith(b"join_") and f[4] == b"RFLK012304200017"
    s = pr.frame_lk_set_cycle("RFLK012304200017", "constant").split(b"\x00", 4)
    assert s[1:3] == [b"lkSet", b"settings"] and s[4] == b"\x04\x00"

LK_STATUS = bytes.fromhex("52464c4b303132333034323030303137006c6b52656672657368007374617475730000000000005a00000000")

def test_level_keeper_settings_full():
    fr = pr.parse_frame(LK_SETTINGS)
    assert fr.serial == "RFLK012304200017" and fr.topic == "lkRefresh"
    d = pr.decode(pr.DEVICE_LEVEL_KEEPER, fr)
    assert d == {
        "cycle": "constant", "level": "water_high", "level_raw": 5,
        "calibration_needed": True, "refilled_today_ml": 90, "calibration_date": (2019, 1, 1),
        "calibration_remaining_s": 0, "circuit_remaining_s": 0,
        "manual_refill_done_ml": 0, "manual_refill_target_ml": 0,
        "max_refill_time_s": 0, "temporary_off_s": 0, "light": True,
    }, d

def test_level_keeper_status_alert():
    d = pr.decode(pr.DEVICE_LEVEL_KEEPER, pr.parse_frame(LK_STATUS))
    assert d == {"level": "ok", "level_raw": 0, "refilled_today_ml": 90, "refill_time_s": 0}, d
    assert pr.decode(pr.DEVICE_LEVEL_KEEPER, pr.parse_frame(LK_ALERT)) == {"alert_code": 3}

def test_level_keeper_progress_frames():
    s = "RFLK012304200017"
    mk = lambda sub, blob: pr.parse_frame(s.encode() + b"\x00lkRefresh\x00" + sub.encode() + b"\x00\x00" + blob)
    assert pr.decode(pr.DEVICE_LEVEL_KEEPER, mk("manualRefill", bytes.fromhex("0000003200000064"))) == {
        "manual_refill_done_ml": 50, "manual_refill_target_ml": 100}
    assert pr.decode(pr.DEVICE_LEVEL_KEEPER, mk("temporary", bytes.fromhex("0000012c"))) == {"temporary_off_s": 300}
    assert pr.decode(pr.DEVICE_LEVEL_KEEPER, mk("temporary", bytes.fromhex("ffffffff"))) == {"temporary_off_s": 0}
    assert pr.decode(pr.DEVICE_LEVEL_KEEPER, mk("calibration", b"\x1e")) == {"calibration_remaining_s": 30}

def _payload(frame):
    parts = frame.split(b"\x00", 4)
    assert parts[0] == b"RFLK012304200017" and parts[3].startswith(b"join_") and frame.endswith(b"\x00")
    return parts[1].decode(), parts[2].decode(), parts[4][:-1]

def test_level_keeper_command_frames():
    s = "RFLK012304200017"
    assert _payload(pr.frame_lk_set_light(s, True)) == ("lkSet", "light", b"\x01")
    assert _payload(pr.frame_lk_set_light(s, False)) == ("lkSet", "light", b"\x00")
    assert _payload(pr.frame_lk_set_max_refill_time(s, 5)) == ("lkSet", "maxRefillTime", (300).to_bytes(4, "big"))
    assert _payload(pr.frame_lk_set_max_refill_time(s, 99)) == ("lkSet", "maxRefillTime", (3600).to_bytes(4, "big"))
    assert _payload(pr.frame_lk_temporary_off(s, 10)) == ("lkSet", "temporaryOff", (600).to_bytes(4, "big"))
    assert _payload(pr.frame_lk_temporary_off(s, 0)) == ("lkSet", "temporaryOff", b"\x00\x00\x00\x00")
    assert _payload(pr.frame_lk_manual_refill_start(s, 250)) == ("lkManualRefill", "start", (250).to_bytes(4, "big"))
    assert _payload(pr.frame_lk_manual_refill_stop(s)) == ("lkManualRefill", "stop", b"")
    assert _payload(pr.frame_lk_calibration_time(s, 30)) == ("lkCalibration", "time", b"\x1e")
    assert _payload(pr.frame_lk_calibration_start(s)) == ("lkCalibration", "start", b"")
    assert _payload(pr.frame_lk_calibration_value(s, 123)) == ("lkCalibration", "value", (123).to_bytes(4, "big"))
    assert _payload(pr.frame_lk_calibration_reminder(s, "1_month")) == ("lkCalibration", "notification", b"\x02")
    assert _payload(pr.frame_lk_circuit_start(s)) == ("lkCalibration", "circuitStart", b"")
    import datetime
    t = _payload(pr.frame_set_time(s, datetime.datetime(2026, 10, 29, 7, 55, 12)))
    assert t == ("set", "time", bytes.fromhex("07ea0a1d07370c01")), t

def test_get_user_frame():
    f = pr.frame_get_user("RFLK012304200017").split(b"\x00")
    assert f[0] == b"RFLK012304200017" and f[1:3] == [b"get", b"user"] and f[3].startswith(b"join_")

def test_parse_user_drops_account_name():
    fr = pr.parse_frame(b"RFLK012304200017\x00status\x00user\x00\x00someone@example.org\x00\x01\x03\x02\x02")
    assert pr.parse_user(fr) == {"wifi_connected": True, "cloud_connected": True}

def test_thermo_full():
    d = pr.decode(pr.DEVICE_THERMO, pr.parse_frame(TC_SETTINGS))
    assert d == {"temperature": 24.5, "fahrenheit": False, "alarm_low": 23.4, "range_low": 24.3,
                 "heating": False, "alarm_high": 26.7, "range_high": 25.7, "cooling": False,
                 "state": "idle", "sound": False, "light": True}, d

def test_thermo_commands():
    f = pr.frame_tc_set_settings("RFTC012310240015", 24.3, 25.7, 23.4, 26.7).split(b"\x00", 4)
    assert f[0] == b"RFTC012310240015" and f[1:3] == [b"tcSet", b"settings"] and f[3].startswith(b"join_")
    assert f[4] == bytes.fromhex("00005eec" "00006464" "00005b68" "0000684c" "00") + b"\x00", f[4].hex()
    assert pr.frame_tc_light("RFTC012310240015", False).split(b"\x00")[1:3] == [b"tcLight", b"off"]
    assert pr.frame_tc_sound("RFTC012310240015", True).split(b"\x00")[1:3] == [b"tcSound", b"on"]

def test_flare_sizes():
    assert pr.device_type("RFRFM61234567890") == pr.DEVICE_FLARE
    assert pr.device_type("RFRFL21234567890") == pr.DEVICE_FLARE

def test_config_frame_gives_serial():
    fr = pr.parse_frame(FLARE_CONFIG)
    assert (fr.topic, fr.subtopic, fr.serial) == ("refresh", "config", "RFRFS62403220038")
    info = pr.parse_config(fr)
    assert info["serial"] == "RFRFS62403220038" and info["firmware"] == "1.0.0", info

def test_flare_dashboard():
    d = pr.decode(pr.DEVICE_FLARE, pr.parse_frame(FLARE_DASHBOARD))
    assert d["mode"] == "dashboard" and d["temperature"] == 31 and "intensity" not in d, d

def test_flare_precise_real():
    fr = pr.parse_frame(FLARE_PRECISE)
    assert fr.serial == "RFRFS62403220038" and len(FLARE_PRECISE) == 266
    d = pr.decode(pr.DEVICE_FLARE, fr)
    assert d["mode"] == "program" and d["temperature"] == 31 and d["intensity"] == 30, d
    assert d["program"] == "Gemischte Kora75" and d["program_index"] == 0
    assert d["programs"] == ["Gemischte Kora75", "Gpt1", "Gpt2 stable 50%", "Gpt3 60% ziel", "", "", "", ""]
    assert len(d["points"]) == 8 and d["points"][2] == {"time": "11:36", "minute": 696, "levels": [100, 100, 100, 100, 50, 50, 80]}
    assert d["acclimation"] is None

def test_flare_intensity_follows_name_length():
    # renaming the active program shifts all following bytes - intensity must still be found
    fr = pr.parse_frame(FLARE_PRECISE)
    blob = bytearray(fr.blob)
    old = "Gemischte Kora75".encode("utf-16-be"); new = "Riff".encode("utf-16-be")
    i = blob.index(old); blob[i:i + len(old)] = new
    list_len = int.from_bytes(blob[2:4], "big") - (len(old) - len(new)); blob[2:4] = list_len.to_bytes(2, "big")
    d = pr.decode(pr.DEVICE_FLARE, pr.Frame(fr.serial, fr.topic, fr.subtopic, fr.joinid, bytes(blob)))
    assert d["program"] == "Riff" and d["intensity"] == 30 and len(d["points"]) == 8, d

def test_flare_manual_synthetic():
    name = lambda s: s.encode("utf-16-be") + b"\x00\x00"
    presets = name("Tag") + b"\x00" + bytes([10, 20, 30, 40, 50, 60, 70]) + name("Mond") + b"\x01" + bytes([0, 0, 5, 5, 0, 0, 0])
    blob = bytes([29, 0x02, 0xFF, 0xFF, 2]) + presets + bytes([80, 15])
    d = pr.decode(pr.DEVICE_FLARE, pr.Frame("RFRFS62403220038", "rfRefresh", "manualData", "", blob))
    assert {k: d[k] for k in ("mode", "temperature", "manual_time_s", "presets", "program", "levels", "intensity")} == {
        "mode": "manual", "temperature": 29, "manual_time_s": None, "presets": ["Tag", "Mond"],
        "program": "Mond", "levels": [0, 0, 5, 5, 0, 0, 0], "intensity": 15}, d
    # round trip: the update frame must carry exactly the list the device sent
    payload = pr.frame_rf_manual_update("RFRFS62403220038", d["manual_presets"]).split(b"\x00", 4)[4][:-1]
    assert payload == blob[4:], (payload.hex(), blob[4:].hex())

def test_flare_precise_update_roundtrip():
    """Re-encoding the active program unchanged must give the device's own program bytes."""
    fr = pr.parse_frame(FLARE_PRECISE)
    d = pr.decode(pr.DEVICE_FLARE, fr)
    payload = pr.frame_rf_precise_update(fr.serial, d["program_index"], d["program_time_raw"], d["points"], d["intensity"]).split(b"\x00", 4)
    assert payload[1:3] == [b"rfPrecise", b"update"]
    body = payload[4][:-1]
    list_len = int.from_bytes(fr.blob[2:4], "big")
    original = fr.blob[4 + list_len:]          # time, count, points, intensity, 5 acclimation bytes
    assert body[0] == 0 and body[1:] == original[:-5], (body.hex(), original.hex())
    # only the intensity byte changes when the intensity changes
    other = pr.frame_rf_precise_update(fr.serial, 0, d["program_time_raw"], d["points"], 35).split(b"\x00", 4)[4][:-1]
    assert other[:-1] == body[:-1] and other[-1] == 35

def test_flare_timer_and_acclimation_frames():
    s = "RFRFS62403220038"
    p = lambda f: f.split(b"\x00", 4)
    assert p(pr.frame_rf_manual_time(s, 900))[1:3] == [b"rfManual", b"time"] and p(pr.frame_rf_manual_time(s, 900))[4][:-1] == (900).to_bytes(2, "big")
    assert p(pr.frame_rf_manual_time(s, None))[4][:-1] == b"\xff\xff"
    assert p(pr.frame_rf_acclimation(s, 14, 40, 100))[4][:-1] == bytes([14, 40, 100])
    assert p(pr.frame_rf_acclimation(s))[4][:-1] == b"\x00\x00\x00"

def test_flare_commands():
    m = pr.frame_rf_mode("RFRFS62403220038", "off").split(b"\x00")
    assert m[0] == b"RFRFS62403220038" and m[1:3] == [b"rfMode", b"off"] and m[3].startswith(b"join_")
    assert pr.frame_rf_mode("RFRFS62403220038", "program").split(b"\x00")[2] == b"precise"
    s = pr.frame_rf_select_program("RFRFS62403220038", 2).split(b"\x00", 4)
    assert s[1:3] == [b"rfPrecise", b"select"] and s[4] == b"\x02\x00"

def test_flare_dashboard_real():
    d = pr.decode(pr.DEVICE_FLARE, pr.parse_frame(FLARE_DASHBOARD_REAL))
    assert d == {"mode": "dashboard", "temperature": 30}, d

def test_flare_real_program_passes_validation():
    """The device's own program must pass the same checks the device UI applies."""
    d = pr.decode(pr.DEVICE_FLARE, pr.parse_frame(FLARE_PRECISE))
    assert d["points"][0]["minute"] == 0 and d["points"][-1]["minute"] == 1440, d["points"]
    norm = pr.normalize_flare_points([{"time": p["time"], "levels": p["levels"]} for p in d["points"]])
    assert [p["minute"] for p in norm] == [p["minute"] for p in d["points"]]
    assert [p["levels"] for p in norm] == [p["levels"] for p in d["points"]]

def test_flare_point_validation_rejects():
    ok = [0] * 7
    bad = [
        [{"time": "00:00", "levels": ok}],                                    # too few
        [{"time": "00:10", "levels": ok}, {"time": "24:00", "levels": ok}],    # not starting 00:00
        [{"time": "00:00", "levels": ok}, {"time": "23:59", "levels": ok}],    # not ending 24:00
        [{"time": "00:00", "levels": ok}, {"time": "12:00", "levels": ok}, {"time": "12:00", "levels": ok}, {"time": "24:00", "levels": ok}],
        [{"time": "00:00", "levels": [0] * 6}, {"time": "24:00", "levels": ok}],
        [{"time": "00:00", "levels": [101] + [0] * 6}, {"time": "24:00", "levels": ok}],
        [{"time": "00:00", "levels": ok}, {"time": "25:00", "levels": ok}],
        [{"time": "00:00", "levels": ok}] + [{"time": f"{h:02d}:30", "levels": ok} for h in range(24)] +
        [{"time": f"{h:02d}:45", "levels": ok} for h in range(7)] + [{"time": "24:00", "levels": ok}],  # 33 points
    ]
    for points in bad:
        try:
            pr.normalize_flare_points(sorted(points, key=lambda p: p["time"]) if len(points) > 30 else points)
        except (ValueError, KeyError):
            continue
        raise AssertionError(points)

def test_flare_name_and_preview_frames():
    s = "RFRFS62403220038"
    f = pr.frame_rf_program_name(s, 3, "Riff Sommer").split(b"\x00", 4)
    assert f[1:3] == [b"rfPrecise", b"name"]
    assert f[4] == bytes([3]) + "Riff Sommer".encode("utf-16-be") + b"\x00\x00\x00"
    assert pr.frame_rf_program_name(s, 0, "x" * 20).split(b"\x00", 4)[4] == b"\x00" + ("x" * 16).encode("utf-16-be") + b"\x00\x00\x00"
    for start, sub in ((True, b"start"), (False, b"stop")):
        p = pr.frame_rf_preview(s, start).split(b"\x00")
        assert p[1:3] == [b"rfPreview", sub] and p[4:] == [b"", b""], p

# --- Smart feeder (cloud channel), frames from the relay capture 03.11.2026 ----------------------
SF_REPORT = (b"RFSF012309180013\x00sfReport\x00all\x001793701213648\x00" + (
    b'{"mode":"period","periods":[{"time":660,"rotations":1,"days":127},{"time":1200,"rotations":1,"days":127}],'
    b'"sequence":{"frequency":360,"rotations":2},"nextFeeding":{"date":"2026-11-03","time":"20:00","doseValue":100},'
    b'"container":{"value":5000,"size":0,"reminderDays":0,"singleDose":100,"daysToEnd":24},'
    b'"history":[{"date":"2026-11-03","time":"11:22","doseType":"manually","doseValue":0},'
    b'{"date":"2026-11-03","time":"11:00","doseType":"automatically","doseValue":0}],'
    b'"dailyDose":0,"ledStatus":"enabled","feedingButton":"enabled"}') + b"\x00")
SF_LOGIN = b"RFSF012309180013\x00geConnect\x00login\x00\x00" + b'{"key":"xxxx","token":"<token>","email":"<email>","version":"1.1.6"}' + b"\x00"

def test_feeder_type_and_login():
    assert pr.device_type("RFSF012309180013") == pr.DEVICE_FEEDER
    fr = pr.parse_frame(SF_LOGIN)
    info = pr.parse_login(fr)
    assert info == {"serial": "RFSF012309180013", "firmware": "1.1.6", "has_token": True}
    assert "<token>" not in str(info) and "<email>" not in str(info)

def test_feeder_report():
    d = pr.decode(pr.DEVICE_FEEDER, pr.parse_frame(SF_REPORT))
    assert d["mode"] == "schedule" and d["interval_minutes"] == 360 and d["interval_rotations"] == 2
    assert d["schedule"][0] == {"time": "11:00", "minute": 660, "rotations": 1,
                               "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "days_mask": 127}
    assert d["container_g"] == 50.0 and d["single_dose_g"] == 1.0 and d["container_size_g"] == 0.0
    assert d["next_feeding"] == "2026-11-03 20:00" and d["next_feeding_g"] == 1.0 and d["days_to_end"] == 24
    assert d["last_feeding"] == "2026-11-03 11:22" and d["last_feeding_type"] == "manually"
    assert d["led"] is True and d["feeding_button"] is True and d["daily_dose_g"] == 0.0

def test_feeder_logs_and_commands():
    s = "RFSF012309180013"
    fr = pr.parse_frame(b"RFSF012309180013\x00sfLog\x00container\x00\x00" + b'{"container":{"alert":"empty","value":0,"size":0}}' + b"\x00")
    assert pr.decode(pr.DEVICE_FEEDER, fr) == {"container_alert": "empty", "container_empty": True}
    fr = pr.parse_frame(b"RFSF012309180013\x00sfLog\x00dose\x00\x00" + b'{"dose":{"type":"manually","value":100},"container":{"value":4900,"size":0}}' + b"\x00")
    assert pr.decode(pr.DEVICE_FEEDER, fr)["last_dose_event"] == {"type": "manually", "grams": 1.0}
    p = lambda f: f.split(b"\x00", 4)
    f = p(pr.frame_sf_feed(s, 1, "1793701213648"))
    assert f[1:4] == [b"sfExecute", b"manual", b"1793701213648"] and f[4] == b'{"rotations":1}\x00'
    assert p(pr.frame_sf_set_mode(s, "interval"))[4] == b'{"mode":"sequence"}\x00'
    assert p(pr.frame_sf_set_schedule(s, [{"time": "11:00", "rotations": 1, "days": "daily"[:0] or 127},
                                          {"time": "20:00", "rotations": 1, "days": ["mon", "wed"]}]))[4] == \
        b'{"periods":[{"time":660,"rotations":1,"days":127},{"time":1200,"rotations":1,"days":5}]}\x00'
    assert p(pr.frame_sf_set_interval(s, 360, 2))[4] == b'{"sequence":{"frequency":360,"rotations":2}}\x00'
    assert p(pr.frame_sf_set_flags(s, False, True))[4] == b'{"ledStatus":"disabled","feedingButton":"enabled"}\x00'
    assert p(pr.frame_sf_set_container(s, 50, 0, 1))[4] == b'{"value":5000,"size":0,"singleDose":100}\x00'
    assert p(pr.frame_sf_set_reminder(s, 3))[4] == b'{"reminderDays":3}\x00'
    import datetime
    f = p(pr.frame_cloud_time(s, datetime.datetime(2026, 11, 3, 11, 13, 44)))
    assert f[1:3] == [b"geSet", b"time"] and f[4] == b'{"year":26,"month":11,"day":3,"weekday":2,"hour":11,"minutes":13,"seconds":44}\x00'
    assert p(pr.frame_login_ok(s))[4] == b'{"status":"success","pingInterval":20}\x00'
    assert p(pr.frame_cloud_subscribe(s, "17937"))[1:5] == [b"sfConnect", b"join", b"17937", b"RFSF012309180013\x00"]
    assert p(pr.frame_cloud_get_all(s, "17937"))[1:4] == [b"sfGet", b"all", b"17937"]

if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); n += 1; print("ok ", name)
    print(f"{n} tests passed")
