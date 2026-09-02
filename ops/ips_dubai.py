"""IPS Dubai 2026 expo warm-up — REACH (70%) + LEADS (30%) on act_776404808314031, 2–6 Sep 2026.

Usage (every phase is resume-safe; ops/ips_dubai.json is rewritten after every step):
  python ops/ips_dubai.py form      # Instant Forms LF_AE_IPS-DUBAI_202609 (en_US) + LF_AE_IPS-DUBAI_RU_202609 (ru_RU); Page token minted from the system user, never printed
  python ops/ips_dubai.py upload    # 10 videos (EN/DE/TR/UA/RU x keys/seasons): reuse video_id from w3_full_rollout.json when present, else upload; wait until ready
  python ops/ips_dubai.py build     # 2 campaigns + 2 ad sets + 15 ads (REACH 10 / LEADS 5), ALL born PAUSED; idempotent by name
  python ops/ips_dubai.py review    # poll ad review every 3 min (60 min max) -> activate campaign/adset/all clean ads
  python ops/ips_dubai.py readback  # final readback + append to ops/build_result.json ("batch": "ips-dubai-202609")
  python ops/ips_dubai.py status    # summary table (offline)

Options:
  --budget-sec N   stop cleanly (state saved) before N seconds elapsed; re-run to continue (default 560)
  --workers N      parallel video uploads (default 2 — a parallel rollout is uploading with 4)

Artifact: ops/ips_dubai.json  {"form", "geo", "uploads", "campaigns", "ads":[...], "review", "activation", "readback", "errors"}
Registry: ops/build_result.json gets the two campaigns with "batch": "ips-dubai-202609".
Token is never printed (common.mask).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Api, mask  # noqa: E402

OPS = Path(__file__).resolve().parent
STATE_PATH = OPS / "ips_dubai.json"
LOG_PATH = OPS / "ips_dubai.log"
REGISTRY_PATH = OPS / "build_result.json"
W3_STATE_PATH = OPS / "w3_full_rollout.json"
V3_STATE_PATH = OPS / "v3_rollout.json"
ASSETS = Path(r"C:\Users\avshc\OneDrive\Desktop\Melia Reels\Wave 3")

BATCH = "ips-dubai-202609"
STATICS_BATCH = "ips-dubai-202609-statics"  # add-only wave 2 (expo statics + bonus video), 2026-09-02
STATICS_ASSETS = Path(r"C:\Users\avshc\OneDrive\Desktop\Melia Reels\IPS Dubai 2026")
EXPECTED_ACCOUNT = "act_776404808314031"
IG_USER_ID = "17841475384506205"
LINK = "https://meliabudva.com"
END_TIME = "2026-09-06T23:59:00+04:00"  # Asia/Dubai
LANGS = ("EN", "DE", "TR", "UA", "RU")  # RU added 2026-09-02 (owner decision)
REVIEW_POLL_SEC = 180
REVIEW_MAX_MIN = 60
PENDING_STATES = ("PENDING_REVIEW", "IN_PROCESS")
BLOCKED_STATES = ("DISAPPROVED", "WITH_ISSUES")

EVENT = {
    "name": "IPS 2026",
    "dates": "7–9 September 2026",
    "hours": "10:00–18:00",
    "venue": "Dubai World Trade Centre, Halls 2–8",
    "stand": "E25",
}

# --- geo (resolved live on 2026-09-02 via GET /search?type=adgeolocation) -------------------------
CITY = {"key": "368", "name": "Dubai", "type": "city", "country_code": "AE"}
PIN_REQUESTS = [
    "Dubai World Trade Centre", "Downtown Dubai", "Business Bay", "DIFC", "Dubai Marina", "Palm Jumeirah",
    "Jumeirah", "Emirates Hills", "Al Barari", "Nad Al Sheba", "Mirdif",
]
# No `place` hits for any of the 11 names -> no radius pins possible; these are the neighborhood keys that
# resolved (type=neighborhood, country AE). Neighborhoods carry no radius in Meta targeting.
NEIGHBORHOODS = [
    {"key": "2933192", "name": "Za'abeel Second", "requested": "Dubai World Trade Centre", "note": "DWTC lies in Za'abeel 2 (DIFC as well)"},
    {"key": "2933197", "name": "Marsa Dubai", "requested": "Dubai Marina", "note": "official community name of Dubai Marina"},
    {"key": "2933616", "name": "Jumeirah Palm", "requested": "Palm Jumeirah"},
    {"key": "2933199", "name": "Jumeira First", "requested": "Jumeirah"},
    {"key": "2933158", "name": "Al Jumeira Second", "requested": "Jumeirah"},
    {"key": "2933179", "name": "Jumeira Third", "requested": "Jumeirah"},
    {"key": "2933160", "name": "Nadd Al Shiba First", "requested": "Nad Al Sheba"},
    {"key": "2933181", "name": "Nadd Al Shiba Second", "requested": "Nad Al Sheba"},
    {"key": "2933200", "name": "Nadd Al Shiba Third", "requested": "Nad Al Sheba"},
    {"key": "2933580", "name": "Nadd Al Shiba Fourth", "requested": "Nad Al Sheba"},
    {"key": "2933326", "name": "Mirdif", "requested": "Mirdif"},
]
UNRESOLVED_PINS = ["Downtown Dubai", "Business Bay", "DIFC", "Emirates Hills", "Al Barari"]

# --- copy (EN master; DE/TR/UA translations keep the compliance wording) --------------------------
TEXTS = {
    "EN": {
        "title": "Meet Meliá Budva at IPS Dubai — Stand E25",
        "message": "Adriatic first-line branded residences, from €263,200 (indicative) · 20% down, interest-free until Q4 2027. "
                   "Meet our team at IPS 2026, Dubai World Trade Centre, Halls 2–8, Stand E25 · 7–9 September, 10:00–18:00.",
        "leads_tail": "Book your meeting at Stand E25 →",
    },
    "DE": {
        "title": "Treffen Sie Meliá Budva auf der IPS Dubai — Stand E25",
        "message": "Branded Residences in erster Meereslinie an der Adria, ab €263.200 (unverbindlich) · 20% Anzahlung, zinsfrei bis Q4 2027. "
                   "Unser Team erwartet Sie auf der IPS 2026, Dubai World Trade Centre, Hallen 2–8, Stand E25 · 7.–9. September, 10:00–18:00.",
        "leads_tail": "Buchen Sie Ihren Termin am Stand E25 →",
    },
    "TR": {
        "title": "Meliá Budva ile IPS Dubai'de buluşun — Stant E25",
        "message": "Adriyatik'te denize sıfır markalı rezidanslar, €263.200'den (gösterge niteliğinde) · %20 peşinat, Q4 2027'ye kadar faizsiz. "
                   "Ekibimiz IPS 2026'da, Dubai World Trade Centre, Salon 2–8, Stant E25 · 7–9 Eylül, 10:00–18:00.",
        "leads_tail": "Stant E25'te görüşme randevunuzu ayırtın →",
    },
    "UA": {
        "title": "Зустріньте Meliá Budva на IPS Dubai — стенд E25",
        "message": "Брендовані резиденції на першій лінії Адріатики, від €263 200 (орієнтовно) · 20% перший внесок, без відсотків до Q4 2027. "
                   "Наша команда на IPS 2026, Dubai World Trade Centre, зали 2–8, стенд E25 · 7–9 вересня, 10:00–18:00.",
        "leads_tail": "Забронюйте зустріч на стенді E25 →",
    },
    "RU": {
        "title": "Meliá Budva на IPS Dubai — стенд E25",
        "message": "Брендированные резиденции на первой линии Адриатики, от €263 200 (ориентировочно) · 20% первый взнос, без процентов до Q4 2027. "
                   "Наша команда на IPS 2026, Dubai World Trade Centre, залы 2–8, стенд E25 · 7–9 сентября, 10:00–18:00.",
        "leads_tail": "Запишитесь на встречу на стенде E25 →",
    },
}

# Custom question keys are IDENTICAL in both forms (CRM attribution): `expo_meeting` + `budget`.
# Never `purpose` / `deal_type` (reserved in CRM).
FORMS: dict[str, dict] = {
    "EN": {
        "name": "LF_AE_IPS-DUBAI_202609", "locales": ["en_US", "EN_US"],
        "privacy": {"url": "https://kvadra.me/privacy", "link_text": "Privacy Policy"},
        "questions": [
            {"type": "FULL_NAME", "key": "full_name", "label": "Full name"},
            {"type": "PHONE", "key": "phone", "label": "Phone number"},
            {"type": "EMAIL", "key": "email", "label": "Email"},
            {
                "type": "CUSTOM", "key": "expo_meeting", "label": "Book a meeting at Stand E25 (IPS Dubai, 7–9 Sept)",
                "options": [
                    {"key": "meeting_1", "value": "September 7"},
                    {"key": "meeting_2", "value": "September 8"},
                    {"key": "meeting_3", "value": "September 9"},
                    {"key": "meeting_4", "value": "Send me the presentation instead"},
                ],
            },
            {
                "type": "CUSTOM", "key": "budget", "label": "Purchase budget",
                "options": [
                    {"key": "budget_1", "value": "Up to €250,000"},
                    {"key": "budget_2", "value": "€250,000–400,000"},
                    {"key": "budget_3", "value": "€400,000–700,000"},
                    {"key": "budget_4", "value": "Over €700,000"},
                ],
            },
        ],
    },
    "RU": {
        "name": "LF_AE_IPS-DUBAI_RU_202609", "locales": ["ru_RU", "RU_RU", "en_US"],
        "privacy": {"url": "https://kvadra.me/privacy", "link_text": "Политика конфиденциальности"},
        "questions": [
            {"type": "FULL_NAME", "key": "full_name", "label": "Имя и фамилия"},
            {"type": "PHONE", "key": "phone", "label": "Номер телефона"},
            {"type": "EMAIL", "key": "email", "label": "Электронная почта"},
            {
                "type": "CUSTOM", "key": "expo_meeting", "label": "Записаться на встречу на стенде E25 (IPS Dubai, 7–9 сентября)",
                "options": [
                    {"key": "meeting_1", "value": "7 сентября"},
                    {"key": "meeting_2", "value": "8 сентября"},
                    {"key": "meeting_3", "value": "9 сентября"},
                    {"key": "meeting_4", "value": "Пришлите презентацию"},
                ],
            },
            {
                "type": "CUSTOM", "key": "budget", "label": "Бюджет покупки",
                "options": [
                    {"key": "budget_1", "value": "До €250 000"},
                    {"key": "budget_2", "value": "€250 000–400 000"},
                    {"key": "budget_3", "value": "€400 000–700 000"},
                    {"key": "budget_4", "value": "Более €700 000"},
                ],
            },
        ],
    },
}


def form_lang_for(lang: str) -> str:
    return "RU" if lang == "RU" else "EN"

CAMPAIGNS: dict[str, dict] = {
    "REACH": {
        "name": "MB_EXPO_IPS-DUBAI_REACH_202609", "objective": "OUTCOME_AWARENESS",
        "adset_name": "AE-DUBAI_REACH_EXPO", "daily_budget": 7000, "advantage_audience": 0, "age_min": 28,
        "adset_extra": {
            "optimization_goal": "REACH", "billing_event": "IMPRESSIONS",
            "frequency_control_specs": json.dumps([{"event": "IMPRESSIONS", "interval_days": 5, "max_frequency": 3}]),
        },
    },
    "LEADS": {
        "name": "MB_EXPO_IPS-DUBAI_LEADS_202609", "objective": "OUTCOME_LEADS",
        "adset_name": "AE-DUBAI_LEADS_EXPO", "daily_budget": 3000, "advantage_audience": 1,
        # validate_only 2026-09-02: with advantage_audience=1 Meta caps the hard minimum-age control at 25
        # (age_min 28 -> subcode 1870188 "add a higher minimum age as a suggestion instead"); 28–65 goes in as a suggestion.
        "age_min": 25, "age_suggestion": [28, 65],
        "age_note": "advantage_audience=1: hard age_min capped at 25 by Meta (28 rejected, subcode 1870188); 28–65 sent as age_range suggestion",
        "adset_extra": {"optimization_goal": "LEAD_GENERATION", "billing_event": "IMPRESSIONS", "destination_type": "ON_AD"},
    },
}

CONCEPT_FILES = {"keys": ("03-keys-2027", "W3-03_{lang}_9x16.mp4"), "seasons": ("01-seasons-alive", "W3-01_{lang}_9x16.mp4")}


def ad_plan() -> list[dict]:
    plan = []
    for lang in LANGS:
        for concept in ("keys", "seasons"):
            plan.append({"campaign": "REACH", "lang": lang, "concept": concept, "name": f"EXPO_ips-dubai_{concept}_VID916_{lang}_E1"})
    for lang in LANGS:
        plan.append({"campaign": "LEADS", "lang": lang, "concept": "keys", "name": f"EXPO_ips-dubai_keys_VID916_{lang}_L1"})
    return plan


def file_for(lang: str, concept: str) -> Path:
    folder, pattern = CONCEPT_FILES[concept]
    base = ASSETS if lang == "EN" else ASSETS / lang
    return base / folder / pattern.format(lang=lang)


def targeting_spec(key: str, with_pins: bool, with_age_suggestion: bool = True) -> dict:
    spec = CAMPAIGNS[key]
    geo: dict = {"cities": [{"key": CITY["key"]}], "location_types": ["home", "recent"]}
    if with_pins:
        geo["neighborhoods"] = [{"key": n["key"]} for n in NEIGHBORHOODS]
    t = {"geo_locations": geo, "age_min": spec["age_min"], "age_max": 65, "targeting_automation": {"advantage_audience": spec["advantage_audience"]}}
    if with_age_suggestion and spec.get("age_suggestion"):
        t["age_range"] = spec["age_suggestion"]
    return t


# ----------------------------------------------------------------------------
DEADLINE = [float("inf")]
_state_lock = threading.Lock()


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def out_of_budget() -> bool:
    return time.time() > DEADLINE[0]


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "batch": BATCH,
        "account": EXPECTED_ACCOUNT,
        "created_utc": now_utc(),
        "api_version": None,
        "event": EVENT,
        "window": {"start": "now (at activation)", "end_time": END_TIME, "tz": "Asia/Dubai"},
        "geo": {"city": CITY, "neighborhoods": NEIGHBORHOODS, "unresolved_pins": UNRESOLVED_PINS, "pins_requested": PIN_REQUESTS,
                "note": "no adgeolocation `place` hits for any requested pin -> no 3 km radius pins; resolved neighborhoods added (no radius); city covers the rest"},
        "phase_log": [],
        "forms": {},
        "uploads": {"videos": {}},
        "campaigns": {},
        "ads": [],
        "review": {"started_utc": None, "polls": [], "distribution": {}, "clean": False},
        "activation": {"done": False, "done_utc": None, "activated_ads": 0, "not_activated": [], "objects": []},
        "readback": {},
        "errors": [],
        "registry_appended": False,
    }


def save_state(state: dict) -> None:
    with _state_lock:
        state["updated_utc"] = now_utc()
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        for _ in range(40):
            try:
                tmp.replace(STATE_PATH)
                return
            except PermissionError:  # Windows: a concurrent reader (inspection, editor) blocks the rename for a moment
                time.sleep(0.25)
        STATE_PATH.write_text(payload, encoding="utf-8")  # last resort: direct (non-atomic) write


def mark_phase(state: dict, phase: str, note: str) -> None:
    state["phase_log"].append({"phase": phase, "ts": now_utc(), "note": note})
    save_state(state)


def add_error(state: dict, **rec) -> None:
    rec["ts"] = now_utc()
    state["errors"].append(rec)
    save_state(state)


def get_many(api: Api, ids: list[str], fields: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        out.update(api.graph("GET", "", {"ids": ",".join(chunk), "fields": fields}))
    return out


def post_variants(api: Api, path: str, variants: list[tuple[str, dict]]) -> tuple[dict, str]:
    """Try POST variants in order; return (response, label) of the first that succeeds."""
    errors = []
    for label, data in variants:
        try:
            return api.graph("POST", path, data=data), label
        except RuntimeError as exc:
            msg = str(exc)
            errors.append(f"{label}: {msg[:300]}")
            log(f"    variant '{label}' rejected: {msg[:220]}")
    raise RuntimeError("all variants failed: " + " | ".join(errors))


# ----------------------------------------------------------------------------
def page_token(api: Api) -> str:
    r = api.graph("GET", api.page_id, {"fields": "id,name,access_token"})
    assert r.get("id") == api.page_id, f"page mismatch {r.get('id')}"
    tok = r.get("access_token")
    assert tok, "no page access_token minted (system user lacks page task?)"
    log(f"form: page token minted for {r.get('name')} ({mask(tok)})")
    return tok


def phase_form(api: Api, state: dict) -> None:
    todo = [fl for fl in FORMS if not state["forms"].get(fl, {}).get("id")]
    if not todo:
        log(f"form: already have {[(fl, f['id']) for fl, f in state['forms'].items()]} — skip")
        return
    pt = page_token(api)
    papi = Api()
    papi.token = pt
    page_forms = papi.get_all(f"{api.page_id}/leadgen_forms", {"fields": "id,name,status,created_time"})
    for fl in todo:
        spec = FORMS[fl]
        existing = [f for f in page_forms if f.get("name") == spec["name"]]
        if existing:
            f = existing[0]
            state["forms"][fl] = {"id": f["id"], "name": spec["name"], "reused": True, "status": f.get("status"), "ts": now_utc()}
            save_state(state)
            log(f"form: {fl}: reusing existing {spec['name']} -> {f['id']}")
        else:
            # Meta: "Parameter label cannot be specified for non-custom questions" (subcode 1892063) —
            # standard questions get their label from `locale`; only CUSTOM questions carry label/options.
            q_keyed = [q if q["type"] == "CUSTOM" else {"type": q["type"], "key": q["key"]} for q in spec["questions"]]
            q_bare = [q if q["type"] == "CUSTOM" else {"type": q["type"]} for q in spec["questions"]]
            base = {
                "name": spec["name"],
                "privacy_policy": json.dumps(spec["privacy"], ensure_ascii=False),
                "is_optimized_for_quality": "true",
                "is_phone_sms_verify_enabled": "true",
                "follow_up_action_url": LINK,
            }
            variants = []
            for sms in ("true", "false"):
                for loc in spec["locales"]:
                    for qlabel, qs in (("keyed", q_keyed), ("bare", q_bare)):
                        variants.append((f"{loc} {'sms' if sms == 'true' else 'no-sms'} {qlabel}",
                                         {**base, "locale": loc, "is_phone_sms_verify_enabled": sms, "questions": json.dumps(qs, ensure_ascii=False)}))
            resp, label = post_variants(papi, f"{api.page_id}/leadgen_forms", variants)
            state["forms"][fl] = {"id": resp["id"], "name": spec["name"], "reused": False, "variant": label,
                                  "locale_sent": label.split(" ")[0], "sms_verify": "no-sms" not in label, "ts": now_utc()}
            save_state(state)
            log(f"form: {fl}: created {spec['name']} -> {resp['id']} via '{label}'")
        rb = api.graph("GET", state["forms"][fl]["id"], {"fields": "id,name,locale,status,questions,follow_up_action_url,is_optimized_for_quality,leads_count"})
        state["forms"][fl]["readback"] = rb
        save_state(state)
        qs = [(q.get("type"), q.get("key"), len(q.get("options", []) or [])) for q in rb.get("questions", [])]
        log(f"form: {fl}: readback {rb.get('id')} locale={rb.get('locale')} status={rb.get('status')} quality={rb.get('is_optimized_for_quality')} questions={qs}")
        keys = {q.get("key") for q in rb.get("questions", []) if q.get("type") == "CUSTOM"}
        assert keys == {"expo_meeting", "budget"}, f"{fl}: custom keys mismatch {keys}"
    mark_phase(state, "form", f"forms {[(fl, f['id']) for fl, f in state['forms'].items()]}")


# ----------------------------------------------------------------------------
def w3_videos() -> dict[str, dict]:
    try:
        return json.loads(W3_STATE_PATH.read_text(encoding="utf-8")).get("uploads", {}).get("videos", {})
    except Exception as exc:  # the other rollout may be mid-write
        log(f"upload: could not read w3 state ({exc}); ignoring")
        return {}


def needed_videos() -> dict[str, Path]:
    return {file_for(p["lang"], p["concept"]).name: file_for(p["lang"], p["concept"]) for p in ad_plan()}


def adopt_from_w3(state: dict, fname: str) -> bool:
    rec = w3_videos().get(fname)
    if rec and rec.get("video_id"):
        state["uploads"]["videos"][fname] = {"video_id": rec["video_id"], "status": "uploaded", "source": "w3_full_rollout.json",
                                             "size_mb": rec.get("size_mb"), "ts": now_utc()}
        save_state(state)
        log(f"upload: {fname} -> reuse video_id {rec['video_id']} from w3_full_rollout.json")
        return True
    return False


def upload_one(fname: str, path: Path, state: dict) -> None:
    if adopt_from_w3(state, fname):  # re-check right before spending bandwidth
        return
    api = Api()
    t0 = time.time()
    with open(path, "rb") as fh:
        resp = api.graph("POST", f"{api.account}/advideos", data={"name": fname}, files={"source": (fname, fh, "video/mp4")}, timeout=1200)
    state["uploads"]["videos"][fname] = {"video_id": resp["id"], "status": "uploaded", "source": "uploaded",
                                         "size_mb": round(path.stat().st_size / 1048576, 1), "upload_sec": round(time.time() - t0), "ts": now_utc()}
    save_state(state)
    log(f"upload: {fname} -> id {resp['id']} ({round(time.time() - t0)}s)")


def phase_upload(api: Api, state: dict, workers: int) -> None:
    files = needed_videos()
    for fname, path in files.items():
        assert path.exists(), f"missing asset {path}"
    for fname in files:
        if not state["uploads"]["videos"].get(fname, {}).get("video_id"):
            adopt_from_w3(state, fname)
    todo = [(f, p) for f, p in files.items() if not state["uploads"]["videos"].get(f, {}).get("video_id")]
    log(f"upload: {len(files)} videos needed, {len(files) - len(todo)} already have ids, {len(todo)} to upload with {workers} workers")
    if todo:
        queue = list(todo)
        qlock = threading.Lock()

        def worker() -> None:
            while True:
                with qlock:
                    if not queue or out_of_budget():
                        return
                    fname, path = queue.pop(0)
                try:
                    upload_one(fname, path, state)
                except Exception as exc:
                    log(f"upload: {fname} FAILED {str(exc)[:300]}")
                    add_error(state, stage="upload", file=fname, error=str(exc)[:500])

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if queue:
            log(f"upload: {len(queue)} videos not started (budget) — re-run to continue")

    pending = {f: r for f, r in state["uploads"]["videos"].items() if r.get("video_id") and r.get("status") != "ready"}
    while pending:
        if out_of_budget():
            log(f"upload: budget exhausted while {len(pending)} videos processing — re-run to continue")
            return
        infos = get_many(api, [r["video_id"] for r in pending.values()], "status")
        for fname, rec in list(pending.items()):
            vs = ((infos.get(rec["video_id"]) or {}).get("status") or {}).get("video_status")
            if vs == "ready":
                rec["status"] = "ready"
                rec["ready_utc"] = now_utc()
                pending.pop(fname)
                log(f"upload: {fname} ready ({rec['video_id']})")
            elif vs == "error":
                rec["status"] = "error"
                pending.pop(fname)
                add_error(state, stage="video_processing", file=fname, video_id=rec["video_id"], error="video_status=error")
                log(f"upload: {fname} PROCESSING ERROR")
        save_state(state)
        if pending:
            log(f"upload: waiting for {len(pending)} videos to process...")
            time.sleep(15)
    ready = sum(1 for r in state["uploads"]["videos"].values() if r.get("status") == "ready")
    log(f"upload: {ready}/{len(files)} videos ready")
    if ready == len(files):
        mark_phase(state, "upload", f"{ready} videos ready")


# ----------------------------------------------------------------------------
def load_full_dof_spec() -> dict | None:
    """The full OPT_OUT creative_features_spec as read back from a live July-2026 creative."""
    try:
        v3 = json.loads(V3_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    stack = [v3]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            d = cur.get("degrees_of_freedom_spec")
            if isinstance(d, dict) and len((d.get("creative_features_spec") or {})) > 5:
                return d
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


SIMPLE_DOF = {"creative_features_spec": {"advantage_plus_creative": {"enroll_status": "OPT_OUT"}}}


def verify_city(api: Api, state: dict) -> None:
    res = api.graph("GET", "search", {"type": "adgeolocation", "q": "Dubai", "location_types": json.dumps(["city"]), "limit": 5}).get("data", [])
    hit = next((r for r in res if r.get("type") == "city" and r.get("country_code") == "AE" and r.get("name") == "Dubai"), None)
    assert hit and hit.get("key") == CITY["key"], f"Dubai city key changed? {hit}"
    state["geo"]["city_verified_utc"] = now_utc()
    save_state(state)
    log(f"build: geo city verified: {hit.get('name')} key {hit.get('key')} ({hit.get('country_code')})")


def find_campaign(api: Api, name: str) -> dict | None:
    rows = api.get_all(f"{api.account}/campaigns", {
        "fields": "id,name,status,effective_status,objective",
        "filtering": json.dumps([{"field": "name", "operator": "CONTAIN", "value": "MB_EXPO_IPS-DUBAI"}]),
    })
    for c in rows:
        if c.get("name") == name and c.get("effective_status") not in ("DELETED", "ARCHIVED") and c.get("status") != "DELETED":
            return c
    return None


def ensure_campaign(api: Api, state: dict, key: str) -> dict:
    spec = CAMPAIGNS[key]
    rec = state["campaigns"].setdefault(key, {"name": spec["name"], "adset_name": spec["adset_name"], "daily_budget": spec["daily_budget"], "objective": spec["objective"]})
    if rec.get("campaign_id"):
        return rec
    live = find_campaign(api, spec["name"])
    if live:
        rec.update({"campaign_id": live["id"], "campaign_adopted": True, "campaign_status": live.get("status")})
        save_state(state)
        log(f"build: {key}: adopted existing campaign {live['id']} ({live.get('status')}/{live.get('effective_status')})")
        return rec
    base = {"name": spec["name"], "objective": spec["objective"], "status": "PAUSED", "special_ad_categories": "[]",
            "buying_type": "AUCTION", "is_adset_budget_sharing_enabled": "false"}
    variants = [("abo-explicit", base), ("plain", {k: v for k, v in base.items() if k != "is_adset_budget_sharing_enabled"})]
    resp, label = post_variants(api, f"{api.account}/campaigns", variants)
    chk = api.graph("GET", resp["id"], {"fields": "status,effective_status,objective,name"})
    assert chk.get("status") == "PAUSED", f"campaign {resp['id']} status={chk.get('status')}"
    rec.update({"campaign_id": resp["id"], "campaign_variant": label, "campaign_status": chk.get("status"), "campaign_created_utc": now_utc()})
    save_state(state)
    log(f"build: {key}: campaign {spec['name']} -> {resp['id']} PAUSED [{chk.get('effective_status')}] via '{label}'")
    return rec


def ensure_adset(api: Api, state: dict, key: str) -> dict:
    spec = CAMPAIGNS[key]
    rec = state["campaigns"][key]
    if rec.get("adset_id"):
        return rec
    live = api.get_all(f"{rec['campaign_id']}/adsets", {"fields": "id,name,status,effective_status,daily_budget,end_time"})
    hit = next((a for a in live if a.get("name") == spec["adset_name"] and a.get("effective_status") not in ("DELETED", "ARCHIVED")), None)
    if hit:
        rec.update({"adset_id": hit["id"], "adset_adopted": True, "adset_status": hit.get("status")})
        save_state(state)
        log(f"build: {key}: adopted existing adset {hit['id']} ({hit.get('status')}) budget {hit.get('daily_budget')} end {hit.get('end_time')}")
        return rec
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    base = {
        "name": spec["adset_name"], "campaign_id": rec["campaign_id"], "status": "PAUSED",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "daily_budget": str(spec["daily_budget"]),
        "promoted_object": json.dumps({"page_id": api.page_id}),
        "start_time": start, "end_time": END_TIME,
        **spec["adset_extra"],
    }
    t_variants = [("city+neighborhoods", targeting_spec(key, True)), ("city-only", targeting_spec(key, False))]
    if spec.get("age_suggestion"):  # the age_range suggestion field is undocumented: also try without it
        t_variants = [
            ("city+neighborhoods", targeting_spec(key, True)), ("city+neighborhoods no-age_range", targeting_spec(key, True, False)),
            ("city-only", targeting_spec(key, False)), ("city-only no-age_range", targeting_spec(key, False, False)),
        ]
    variants = [(label, {**base, "targeting": json.dumps(t)}) for label, t in t_variants]
    if key == "REACH":
        variants += [(f"{label} no-promoted_object", {k: v for k, v in data.items() if k != "promoted_object"}) for label, data in list(variants)]
    # validate first (no object created), then the real create with the variant that validated
    ok_label = None
    for label, data in variants:
        try:
            api.graph("POST", f"{api.account}/adsets", data={**data, "execution_options": json.dumps(["validate_only"])})
            ok_label = label
            log(f"build: {key}: adset variant '{label}' validated")
            break
        except RuntimeError as exc:
            log(f"build: {key}: adset variant '{label}' rejected on validate: {str(exc)[:220]}")
    if ok_label is None:
        raise RuntimeError(f"{key}: no adset variant validates")
    ordered = [v for v in variants if v[0] == ok_label] + [v for v in variants if v[0] != ok_label]
    resp, label = post_variants(api, f"{api.account}/adsets", ordered)
    chk = api.graph("GET", resp["id"], {"fields": "status,effective_status,daily_budget,end_time,optimization_goal,billing_event,bid_strategy,targeting,frequency_control_specs,promoted_object,start_time"})
    assert chk.get("status") == "PAUSED", f"adset {resp['id']} status={chk.get('status')}"
    rec.update({
        "adset_id": resp["id"], "adset_variant": label, "pins_applied": label.startswith("city+neighborhoods"),
        "adset_status": chk.get("status"), "adset_created_utc": now_utc(),
        "targeting_used": chk.get("targeting"), "adset_readback": {k: chk.get(k) for k in ("daily_budget", "end_time", "start_time", "optimization_goal", "billing_event", "bid_strategy", "frequency_control_specs", "promoted_object")},
    })
    save_state(state)
    log(f"build: {key}: adset {spec['adset_name']} -> {resp['id']} PAUSED budget {chk.get('daily_budget')} end {chk.get('end_time')} via '{label}'")
    return rec


def fresh_thumbnail(api: Api, video_id: str) -> str:
    for _ in range(12):
        thumbs = api.get_all(f"{video_id}/thumbnails", {"fields": "uri,is_preferred"})
        if thumbs:
            pref = next((t for t in thumbs if t.get("is_preferred")), thumbs[0])
            return pref["uri"]
        time.sleep(10)
    raise RuntimeError(f"no thumbnails for video {video_id} after 2 min")


def creative_for(api: Api, state: dict, item: dict, dof_modes: list[tuple[str, dict | None]]) -> tuple[str, str]:
    lang, concept, key = item["lang"], item["concept"], item["campaign"]
    txt = TEXTS[lang]
    fname = file_for(lang, concept).name
    vrec = state["uploads"]["videos"][fname]
    assert vrec.get("status") == "ready", f"video {fname} not ready"
    if key == "REACH":
        cta = {"type": "LEARN_MORE", "value": {"link": LINK}}
        message = txt["message"]
    else:
        cta = {"type": "SIGN_UP", "value": {"lead_gen_form_id": state["forms"][form_lang_for(lang)]["id"]}}
        message = f"{txt['message']} {txt['leads_tail']}"
    thumb = fresh_thumbnail(api, vrec["video_id"])  # fresh, immediately before the create call
    oss = {
        "page_id": api.page_id,
        "instagram_user_id": IG_USER_ID,
        "video_data": {"video_id": vrec["video_id"], "image_url": thumb, "title": txt["title"], "message": message, "call_to_action": cta},
    }
    base = {"name": f"{item['name']}_cr {BATCH}", "object_story_spec": json.dumps(oss, ensure_ascii=False)}
    variants = []
    for label, dof in dof_modes:
        variants.append((label, {**base, "degrees_of_freedom_spec": json.dumps(dof)} if dof else dict(base)))
    resp, label = post_variants(api, f"{api.account}/adcreatives", variants)
    return resp["id"], label


def live_ads(api: Api, adset_id: str) -> dict[str, dict]:
    ads = api.get_all(f"{adset_id}/ads", {"fields": "id,name,status,effective_status,creative{id}"})
    return {a["name"]: a for a in ads if a.get("effective_status") not in ("DELETED", "ARCHIVED") and a.get("status") != "DELETED"}


def phase_build(api: Api, state: dict) -> None:
    assert all(state["forms"].get(fl, {}).get("id") for fl in FORMS), "run form first (EN + RU forms)"
    files = needed_videos()
    not_ready = [f for f in files if state["uploads"]["videos"].get(f, {}).get("status") != "ready"]
    assert not not_ready, f"videos not ready: {not_ready} (run upload)"
    state["api_version"] = api.version
    if not state["geo"].get("city_verified_utc"):
        verify_city(api, state)
    for key in CAMPAIGNS:
        ensure_campaign(api, state, key)
        ensure_adset(api, state, key)

    full_dof = load_full_dof_spec()
    dof_modes: list[tuple[str, dict | None]] = []
    if state.get("dof_mode"):
        dof_modes = [(state["dof_mode"], state.get("dof_spec"))]
    else:
        if full_dof:
            dof_modes.append(("full-opt-out", full_dof))
        dof_modes += [("simple-opt-out", SIMPLE_DOF), ("none", None)]

    created = 0
    canary_done = {k: any(a["campaign"] == k for a in state["ads"]) for k in CAMPAIGNS}
    for key in CAMPAIGNS:
        adset_id = state["campaigns"][key]["adset_id"]
        campaign_id = state["campaigns"][key]["campaign_id"]
        names_live = live_ads(api, adset_id)
        for item in [p for p in ad_plan() if p["campaign"] == key]:
            if out_of_budget():
                log("build: budget exhausted — re-run to continue"); save_state(state); return
            name = item["name"]
            if any(a["name"] == name for a in state["ads"]):
                continue
            if name in names_live:  # idempotency by name in adset
                live = names_live[name]
                state["ads"].append({
                    "campaign": key, "campaign_id": campaign_id, "adset_id": adset_id, "name": name, "ad_id": live["id"],
                    "creative_id": (live.get("creative") or {}).get("id"), "type": "video", "lang": item["lang"], "concept": item["concept"],
                    "video_id": state["uploads"]["videos"][file_for(item["lang"], item["concept"]).name]["video_id"],
                    "status": live.get("status"), "effective_status": live.get("effective_status"), "batch": BATCH, "ts": now_utc(), "adopted_pre_existing": True,
                })
                save_state(state)
                log(f"build: {key}/{name}: adopted pre-existing ad {live['id']}")
                continue
            try:
                creative_id, dof_label = creative_for(api, state, item, dof_modes)
                if not state.get("dof_mode"):
                    state["dof_mode"] = dof_label
                    state["dof_spec"] = next(d for l, d in dof_modes if l == dof_label)
                    dof_modes = [(dof_label, state["dof_spec"])]
                    save_state(state)
                    log(f"build: degrees_of_freedom mode locked: {dof_label}")
                data = {"name": name, "adset_id": adset_id, "creative": json.dumps({"creative_id": creative_id}), "status": "PAUSED"}
                if not canary_done[key]:
                    api.graph("POST", f"{api.account}/ads", data={**data, "execution_options": json.dumps(["validate_only"])})
                resp = api.graph("POST", f"{api.account}/ads", data=data)
                chk = api.graph("GET", resp["id"], {"fields": "status,effective_status"})
                assert chk.get("status") == "PAUSED", f"ad {resp['id']} status={chk.get('status')}"
                canary_done[key] = True
                state["ads"].append({
                    "campaign": key, "campaign_id": campaign_id, "adset_id": adset_id, "name": name, "ad_id": resp["id"],
                    "creative_id": creative_id, "type": "video", "lang": item["lang"], "concept": item["concept"],
                    "video_id": state["uploads"]["videos"][file_for(item["lang"], item["concept"]).name]["video_id"],
                    "status": chk.get("status"), "effective_status": chk.get("effective_status"), "batch": BATCH, "ts": now_utc(),
                })
                save_state(state)
                created += 1
                log(f"build: {key}/{name}: ad {resp['id']} (creative {creative_id}) PAUSED [{chk.get('effective_status')}]")
                time.sleep(1.0)
            except Exception as exc:
                add_error(state, stage="build", campaign=key, name=name, error=str(exc)[:500])
                log(f"build: {key}/{name}: ERROR {str(exc)[:400]}")
                if not canary_done[key]:
                    raise SystemExit(f"canary ad for {key} failed — aborting: {exc}")
    log(f"build: created {created} ads this run; {len(state['ads'])}/{len(ad_plan())} tracked")
    if len(state["ads"]) == len(ad_plan()):
        mark_phase(state, "build", f"{len(state['ads'])} ads PAUSED")


# ----------------------------------------------------------------------------
def wave_ads(state: dict, batch: str) -> list[dict]:
    return [a for a in state["ads"] if a.get("batch", BATCH) == batch]


def poll_ads(api: Api, state: dict, ads: list[dict], rv: dict) -> dict[str, int]:
    """Batched ?ids= poll (never the /ads listing edge) of the given ads; updates recs + the review block."""
    infos = get_many(api, [a["ad_id"] for a in ads], "status,effective_status,issues_info,ad_review_feedback")
    dist: dict[str, int] = {}
    for rec in ads:
        info = infos.get(rec["ad_id"]) or {}
        rec["status"] = info.get("status", rec.get("status"))
        rec["effective_status"] = info.get("effective_status", rec.get("effective_status"))
        rec["issues_info"] = info.get("issues_info")
        rec["ad_review_feedback"] = info.get("ad_review_feedback")
        dist[rec["effective_status"]] = dist.get(rec["effective_status"], 0) + 1
    rv["distribution"] = dist
    rv["polls"].append({"ts": now_utc(), "distribution": dist})
    save_state(state)
    return dist


def poll_pool(api: Api, state: dict) -> dict[str, int]:
    return poll_ads(api, state, wave_ads(state, BATCH), state["review"])


def is_blocked(rec: dict) -> bool:
    return rec.get("effective_status") in BLOCKED_STATES or bool(rec.get("ad_review_feedback")) or bool(rec.get("issues_info"))


def phase_review(api: Api, state: dict) -> None:
    assert len(wave_ads(state, BATCH)) == len(ad_plan()), f"only {len(wave_ads(state, BATCH))}/{len(ad_plan())} ads built — run build"
    if state["activation"]["done"]:
        log("review: activation already done"); return
    rv = state["review"]
    if not rv["started_utc"]:
        rv["started_utc"] = now_utc(); save_state(state)
    started = datetime.strptime(rv["started_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    while True:
        dist = poll_pool(api, state)
        pending = sum(dist.get(s, 0) for s in PENDING_STATES)
        blocked = sum(1 for a in wave_ads(state, BATCH) if is_blocked(a))
        elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60
        log(f"review: {dist} | pending {pending} | blocked {blocked} | {elapsed_min:.0f} min since start")
        if pending == 0:
            rv["clean"] = blocked == 0; save_state(state)
            log("review: pool has no PENDING_REVIEW / IN_PROCESS -> activating the clean ads")
            break
        if elapsed_min >= REVIEW_MAX_MIN:
            log(f"review: {pending} ads still in review after {REVIEW_MAX_MIN} min -> activating the clean ones, reporting the rest")
            break
        if time.time() + REVIEW_POLL_SEC > DEADLINE[0]:
            log("review: invocation budget reached — re-run to keep polling"); return
        time.sleep(REVIEW_POLL_SEC)
    activate_all(api, state)


def activate_all(api: Api, state: dict) -> None:
    act = state["activation"]
    act["not_activated"] = []
    act["objects"] = []
    clean_by_key: dict[str, list[dict]] = {k: [] for k in CAMPAIGNS}
    for rec in wave_ads(state, BATCH):
        eff = rec.get("effective_status")
        if is_blocked(rec) or eff in PENDING_STATES:
            act["not_activated"].append({"campaign": rec["campaign"], "name": rec["name"], "ad_id": rec["ad_id"], "effective_status": eff,
                                         "issues_info": rec.get("issues_info"), "ad_review_feedback": rec.get("ad_review_feedback")})
            log(f"activate: SKIP {rec['campaign']}/{rec['name']}: {eff} {json.dumps(rec.get('ad_review_feedback') or rec.get('issues_info') or '', ensure_ascii=False)[:200]}")
            continue
        clean_by_key[rec["campaign"]].append(rec)
    # campaign + adset first (so ads read back as ACTIVE, not CAMPAIGN_PAUSED), then the clean ads
    for key in CAMPAIGNS:
        c = state["campaigns"][key]
        if not clean_by_key[key]:
            log(f"activate: {key}: no clean ads -> campaign/adset left PAUSED")
            continue
        for label, oid in (("campaign", c["campaign_id"]), ("adset", c["adset_id"])):
            try:
                api.graph("POST", oid, data={"status": "ACTIVE"})
                chk = api.graph("GET", oid, {"fields": "status,effective_status"})
                act["objects"].append({"campaign": key, "kind": label, "id": oid, "status": chk.get("status"), "effective_status": chk.get("effective_status"), "ts": now_utc()})
                log(f"activate: {key} {label} {oid} -> {chk.get('status')} [{chk.get('effective_status')}]")
                if chk.get("status") != "ACTIVE":
                    add_error(state, stage="activate", campaign=key, object=label, id=oid, error=f"status after POST = {chk.get('status')}")
            except Exception as exc:
                add_error(state, stage="activate", campaign=key, object=label, id=oid, error=str(exc)[:500])
                log(f"activate: {key} {label} {oid} ERROR {exc}")
        save_state(state)
    activated = 0
    for key in CAMPAIGNS:
        for rec in clean_by_key[key]:
            if rec.get("status") == "ACTIVE":
                activated += 1; continue
            try:
                api.graph("POST", rec["ad_id"], data={"status": "ACTIVE"})
                chk = api.graph("GET", rec["ad_id"], {"fields": "status,effective_status"})
                rec["status"] = chk.get("status"); rec["effective_status"] = chk.get("effective_status"); rec["activated_utc"] = now_utc()
                if chk.get("status") == "ACTIVE":
                    activated += 1
                    log(f"activate: {key}/{rec['name']} -> ACTIVE [{chk.get('effective_status')}]")
                else:
                    add_error(state, stage="activate", campaign=key, name=rec["name"], ad_id=rec["ad_id"], error=f"status after POST = {chk.get('status')}")
                save_state(state)
                time.sleep(0.5)
            except Exception as exc:
                add_error(state, stage="activate", campaign=key, name=rec["name"], ad_id=rec["ad_id"], error=str(exc)[:500])
                log(f"activate: {key}/{rec['name']} ERROR {exc}")
    act["activated_ads"] = activated
    act["done"] = True
    act["done_utc"] = now_utc()
    save_state(state)
    mark_phase(state, "activate", f"{activated} ads ACTIVE, {len(act['not_activated'])} not activated")
    log(f"activate: done — {activated} ads ACTIVE, {len(act['not_activated'])} not activated")


# ----------------------------------------------------------------------------
def phase_readback(api: Api, state: dict) -> None:
    rb: dict = {"ts": now_utc(), "campaigns": {}}
    for key in CAMPAIGNS:
        c = state["campaigns"][key]
        camp = api.graph("GET", c["campaign_id"], {"fields": "id,name,status,effective_status,objective,special_ad_categories,buying_type"})
        adset = api.graph("GET", c["adset_id"], {"fields": "id,name,status,effective_status,daily_budget,bid_strategy,optimization_goal,billing_event,destination_type,start_time,end_time,targeting,frequency_control_specs,promoted_object"})
        ads = api.get_all(f"{c['adset_id']}/ads", {"fields": "id,name,status,effective_status,creative{id}"})
        ads = [a for a in ads if a.get("effective_status") not in ("DELETED", "ARCHIVED")]
        rb["campaigns"][key] = {"campaign": camp, "adset": adset, "ads": ads}
        dist: dict[str, int] = {}
        for a in ads:
            dist[a.get("effective_status")] = dist.get(a.get("effective_status"), 0) + 1
        log(f"readback: {key}: campaign {camp.get('status')}/{camp.get('effective_status')} | adset {adset.get('status')}/{adset.get('effective_status')} "
            f"budget {adset.get('daily_budget')} end {adset.get('end_time')} | ads {len(ads)} {dist}")
        by_id = {a["id"]: a for a in ads}
        for rec in state["ads"]:
            if rec["campaign"] == key and rec["ad_id"] in by_id:
                rec["status"] = by_id[rec["ad_id"]].get("status")
                rec["effective_status"] = by_id[rec["ad_id"]].get("effective_status")
        c["campaign_status"] = f"{camp.get('status')}/{camp.get('effective_status')}"
        c["adset_status"] = f"{adset.get('status')}/{adset.get('effective_status')}"
    state["readback"] = rb
    save_state(state)
    sync_registry(state)
    mark_phase(state, "readback", "ok")


def sync_registry(state: dict) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))  # re-read right before writing (another rollout writes it too)
    by_name = {c["name"]: c for c in registry["campaigns"]}
    added_c = added_a = updated_a = 0
    for key, spec in CAMPAIGNS.items():
        c = state["campaigns"].get(key)
        if not c or not c.get("campaign_id"):
            continue
        entry = by_name.get(spec["name"])
        if entry is None:
            entry = {
                "name": spec["name"], "id": c["campaign_id"], "adset_id": c.get("adset_id"), "batch": BATCH,
                "objective": spec["objective"], "adset_name": spec["adset_name"], "daily_budget": spec["daily_budget"],
                "end_time": END_TIME, "geo": "AE/Dubai city 368 + resolved neighborhoods", "ads": [], "counts": {"video": 0, "image": 0, "total": 0},
            }
            registry["campaigns"].append(entry)
            by_name[spec["name"]] = entry
            added_c += 1
        entry["batch"] = BATCH
        if key == "LEADS" and state["forms"]:
            entry["form_id"] = state["forms"].get("EN", {}).get("id")
            entry["form_ids"] = {fl: f.get("id") for fl, f in state["forms"].items()}
        if state["activation"].get("done"):
            entry["launched"] = {"ts": state["activation"].get("done_utc"), "activated_ads": state["activation"].get("activated_ads")}
        st_act = (state.get("statics") or {}).get("activation") or {}
        if st_act.get("done"):
            entry["launched_statics"] = {"ts": st_act.get("done_utc"), "activated_ads": st_act.get("activated_ads"), "batch": STATICS_BATCH}
        for rec in [a for a in state["ads"] if a["campaign"] == key]:
            existing = next((a for a in entry["ads"] if a.get("ad_id") == rec["ad_id"]), None)
            if existing:
                if existing.get("status") != rec.get("status"):
                    existing["status"] = rec.get("status"); updated_a += 1
                continue
            entry["ads"].append({"name": rec["name"], "ad_id": rec["ad_id"], "creative_id": rec["creative_id"], "type": rec.get("type", "video"),
                                 "status": rec.get("status"), "batch": rec.get("batch", BATCH)})
            added_a += 1
        entry["counts"] = {"video": sum(1 for a in entry["ads"] if a.get("type") == "video"), "image": sum(1 for a in entry["ads"] if a.get("type") == "image"), "total": len(entry["ads"])}
        entry["batches"] = sorted({a.get("batch") for a in entry["ads"] if a.get("batch")})
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state["registry_appended"] = True
    save_state(state)
    log(f"registry: +{added_c} campaigns, +{added_a} ads, {updated_a} status updates in {REGISTRY_PATH.name}")


# ----------------------------------------------------------------------------
# Wave 2 (add-only): expo statics (layout A/B x 5 langs, IMG45) + bonus EN video. Nothing is paused or deleted.
def statics_plan() -> list[dict]:
    plan = []
    for lang in LANGS:
        for layout in ("A", "B"):
            plan.append({"campaign": "REACH", "lang": lang, "kind": "image", "layout": layout, "fmt": "IMG45",
                         "name": f"EXPO_ips-dubai_static-{layout}_IMG45_{lang}_E1", "file": STATICS_ASSETS / lang / f"IPS_{layout}_{lang}_IMG45.png"})
    plan.append({"campaign": "REACH", "lang": "EN", "kind": "video", "layout": None, "fmt": "VID916",
                 "name": "EXPO_ips-dubai_keys-expo_VID916_EN_E1", "file": STATICS_ASSETS / "EN" / "IPS_video_EN_9x16.mp4"})
    for lang in LANGS:
        plan.append({"campaign": "LEADS", "lang": lang, "kind": "image", "layout": "B", "fmt": "IMG45",
                     "name": f"EXPO_ips-dubai_static-B_IMG45_{lang}_L1", "file": STATICS_ASSETS / lang / f"IPS_B_{lang}_IMG45.png"})
    return plan


def statics_block(state: dict) -> dict:
    return state.setdefault("statics", {
        "batch": STATICS_BATCH, "created_utc": now_utc(), "assets": str(STATICS_ASSETS), "manifest": str(STATICS_ASSETS / "INDEX.md"),
        "uploads": {"images": {}, "videos": {}},
        "review": {"started_utc": None, "polls": [], "distribution": {}, "clean": False},
        "activation": {"done": False, "done_utc": None, "activated_ads": 0, "not_activated": [], "parents": []},
        "readback": {}, "registry_appended": False,
    })


def live_ads_safe(api: Api, adset_id: str) -> dict[str, dict] | None:
    """The /ads listing edge may be throttled; after the backoff gives up we fall back to state-only idempotency."""
    try:
        return live_ads(api, adset_id)
    except RuntimeError as exc:
        log(f"statics: /ads listing for {adset_id} unavailable ({str(exc)[:160]}) -> idempotency by state + ?ids= only")
        return None


def statics_creative(api: Api, state: dict, item: dict) -> str:
    blk = statics_block(state)
    lang, key = item["lang"], item["campaign"]
    txt = TEXTS[lang]
    if key == "REACH":
        cta = {"type": "LEARN_MORE", "value": {"link": LINK}}
        message = txt["message"]
    else:
        cta = {"type": "SIGN_UP", "value": {"lead_gen_form_id": state["forms"][form_lang_for(lang)]["id"]}}
        message = f"{txt['message']} {txt['leads_tail']}"
    oss: dict = {"page_id": api.page_id, "instagram_user_id": IG_USER_ID}
    fname = item["file"].name
    if item["kind"] == "image":
        img = blk["uploads"]["images"][fname]
        # link_data.link is mandatory even for lead-form CTAs (subcode 2061015)
        oss["link_data"] = {"image_hash": img["hash"], "link": LINK, "message": message, "name": txt["title"], "call_to_action": cta}
    else:
        vrec = blk["uploads"]["videos"][fname]
        assert vrec.get("status") == "ready", f"video {fname} not ready"
        thumb = fresh_thumbnail(api, vrec["video_id"])  # fresh, immediately before the create call
        oss["video_data"] = {"video_id": vrec["video_id"], "image_url": thumb, "title": txt["title"], "message": message, "call_to_action": cta}
    data = {"name": f"{item['name']}_cr {STATICS_BATCH}", "object_story_spec": json.dumps(oss, ensure_ascii=False)}
    dof = state.get("dof_spec") or load_full_dof_spec() or SIMPLE_DOF
    variants = [("locked-dof", {**data, "degrees_of_freedom_spec": json.dumps(dof)}), ("simple-dof", {**data, "degrees_of_freedom_spec": json.dumps(SIMPLE_DOF)})]
    resp, label = post_variants(api, f"{api.account}/adcreatives", variants)
    if label != "locked-dof":
        log(f"statics: {item['name']}: creative made with '{label}' (full opt-out rejected)")
    return resp["id"]


def phase_statics(api: Api, state: dict) -> None:
    assert all(state["forms"].get(fl, {}).get("id") for fl in FORMS), "forms missing"
    assert all(state["campaigns"].get(k, {}).get("adset_id") for k in CAMPAIGNS), "campaigns/adsets missing"
    blk = statics_block(state)
    plan = statics_plan()
    for it in plan:
        assert it["file"].exists(), f"missing asset {it['file']}"
    save_state(state)

    # --- images: fresh hashes via /adimages (Meta dedups identical bytes to the same hash)
    for it in [p for p in plan if p["kind"] == "image"]:
        fname = it["file"].name
        if blk["uploads"]["images"].get(fname, {}).get("hash"):
            continue
        if out_of_budget():
            log("statics: budget exhausted (images) — re-run to continue"); return
        with open(it["file"], "rb") as fh:
            resp = api.graph("POST", f"{api.account}/adimages", files={"filename": (fname, fh, "image/png")}, timeout=600)
        images = resp.get("images", {})
        info = images.get(fname) or next(iter(images.values()), {})
        assert info.get("hash"), f"no hash in adimages response for {fname}: {json.dumps(resp)[:200]}"
        blk["uploads"]["images"][fname] = {"hash": info["hash"], "size_kb": it["file"].stat().st_size // 1024, "ts": now_utc()}
        save_state(state)
        log(f"statics: image {fname} -> hash {info['hash']}")
        time.sleep(0.5)

    # --- bonus video
    vit = next(p for p in plan if p["kind"] == "video")
    vname = vit["file"].name
    vrec = blk["uploads"]["videos"].get(vname, {})
    if not vrec.get("video_id"):
        if out_of_budget():
            log("statics: budget exhausted (video) — re-run to continue"); return
        t0 = time.time()
        with open(vit["file"], "rb") as fh:
            resp = api.graph("POST", f"{api.account}/advideos", data={"name": vname}, files={"source": (vname, fh, "video/mp4")}, timeout=1800)
        vrec = {"video_id": resp["id"], "status": "uploaded", "size_mb": round(vit["file"].stat().st_size / 1048576, 1), "upload_sec": round(time.time() - t0), "ts": now_utc()}
        blk["uploads"]["videos"][vname] = vrec
        save_state(state)
        log(f"statics: video {vname} -> id {resp['id']} ({vrec['upload_sec']}s)")
    while vrec.get("status") != "ready":
        if out_of_budget():
            log("statics: budget exhausted while video processing — re-run to continue"); return
        vs = ((get_many(api, [vrec["video_id"]], "status").get(vrec["video_id"]) or {}).get("status") or {}).get("video_status")
        if vs == "ready":
            vrec["status"] = "ready"; vrec["ready_utc"] = now_utc(); save_state(state)
            log(f"statics: video {vname} ready ({vrec['video_id']})")
        elif vs == "error":
            vrec["status"] = "error"; save_state(state)
            add_error(state, stage="statics_video", file=vname, video_id=vrec["video_id"], error="video_status=error")
            log(f"statics: video {vname} PROCESSING ERROR — video ad will be skipped"); break
        else:
            log(f"statics: waiting for video processing ({vs})..."); time.sleep(15)

    # --- ads, all PAUSED, idempotent by name (live listing when available, state always)
    created = 0
    canary_done = {"image": any(a.get("type") == "image" for a in wave_ads(state, STATICS_BATCH)),
                   "video": any(a.get("type") == "video" for a in wave_ads(state, STATICS_BATCH))}
    for key in CAMPAIGNS:
        adset_id = state["campaigns"][key]["adset_id"]
        campaign_id = state["campaigns"][key]["campaign_id"]
        names_live = live_ads_safe(api, adset_id)
        for it in [p for p in plan if p["campaign"] == key]:
            if out_of_budget():
                log("statics: budget exhausted (ads) — re-run to continue"); save_state(state); return
            name = it["name"]
            if any(a["name"] == name for a in state["ads"]):
                continue
            if it["kind"] == "video" and blk["uploads"]["videos"].get(it["file"].name, {}).get("status") != "ready":
                add_error(state, stage="statics_build", campaign=key, name=name, error="video not ready"); continue
            base_rec = {"campaign": key, "campaign_id": campaign_id, "adset_id": adset_id, "name": name, "type": it["kind"], "lang": it["lang"],
                        "layout": it["layout"], "fmt": it["fmt"], "file": it["file"].name, "batch": STATICS_BATCH, "wave": "statics"}
            if it["kind"] == "image":
                base_rec["image_hash"] = blk["uploads"]["images"][it["file"].name]["hash"]
            else:
                base_rec["video_id"] = blk["uploads"]["videos"][it["file"].name]["video_id"]
            if names_live and name in names_live:
                live = names_live[name]
                info = get_many(api, [live["id"]], "status,effective_status,creative{id}").get(live["id"]) or {}
                state["ads"].append({**base_rec, "ad_id": live["id"], "creative_id": (info.get("creative") or live.get("creative") or {}).get("id"),
                                     "status": info.get("status"), "effective_status": info.get("effective_status"), "ts": now_utc(), "adopted_pre_existing": True})
                save_state(state)
                log(f"statics: {key}/{name}: adopted pre-existing ad {live['id']}")
                continue
            try:
                creative_id = statics_creative(api, state, it)
                data = {"name": name, "adset_id": adset_id, "creative": json.dumps({"creative_id": creative_id}), "status": "PAUSED"}
                if not canary_done[it["kind"]]:
                    api.graph("POST", f"{api.account}/ads", data={**data, "execution_options": json.dumps(["validate_only"])})
                resp = api.graph("POST", f"{api.account}/ads", data=data)
                chk = get_many(api, [resp["id"]], "status,effective_status").get(resp["id"]) or {}
                assert chk.get("status") == "PAUSED", f"ad {resp['id']} status={chk.get('status')}"
                canary_done[it["kind"]] = True
                state["ads"].append({**base_rec, "ad_id": resp["id"], "creative_id": creative_id, "status": chk.get("status"), "effective_status": chk.get("effective_status"), "ts": now_utc()})
                save_state(state)
                created += 1
                log(f"statics: {key}/{name}: ad {resp['id']} (creative {creative_id}) PAUSED [{chk.get('effective_status')}]")
                time.sleep(1.0)
            except Exception as exc:
                add_error(state, stage="statics_build", campaign=key, name=name, error=str(exc)[:500])
                log(f"statics: {key}/{name}: ERROR {str(exc)[:400]}")
                if not canary_done[it["kind"]]:
                    raise SystemExit(f"statics canary ({it['kind']}) failed — aborting: {exc}")
    have = len(wave_ads(state, STATICS_BATCH))
    log(f"statics: created {created} ads this run; {have}/{len(plan)} tracked")
    if have == len(plan):
        mark_phase(state, "statics", f"{have} ads PAUSED")


def phase_statics_review(api: Api, state: dict) -> None:
    blk = statics_block(state)
    ads = wave_ads(state, STATICS_BATCH)
    assert ads, "no statics ads — run statics"
    if blk["activation"]["done"]:
        log("statics_review: activation already done"); return
    rv = blk["review"]
    if not rv["started_utc"]:
        rv["started_utc"] = now_utc(); save_state(state)
    started = datetime.strptime(rv["started_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    while True:
        dist = poll_ads(api, state, ads, rv)
        pending = sum(dist.get(s, 0) for s in PENDING_STATES)
        blocked = sum(1 for a in ads if is_blocked(a))
        elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60
        log(f"statics_review: {dist} | pending {pending} | blocked {blocked} | {elapsed_min:.0f} min since start")
        if pending == 0:
            rv["clean"] = blocked == 0; save_state(state)
            log("statics_review: no PENDING_REVIEW / IN_PROCESS left -> activating the clean ads"); break
        if elapsed_min >= REVIEW_MAX_MIN:
            log(f"statics_review: {pending} ads still in review after {REVIEW_MAX_MIN} min -> activating the clean ones, reporting the rest"); break
        if time.time() + REVIEW_POLL_SEC > DEADLINE[0]:
            log("statics_review: invocation budget reached — re-run to keep polling"); return
        time.sleep(REVIEW_POLL_SEC)
    activate_statics(api, state)


def activate_statics(api: Api, state: dict) -> None:
    blk = statics_block(state)
    act = blk["activation"]
    act["not_activated"] = []; act["parents"] = []
    # parents must already be ACTIVE (wave 1); verify via ?ids=, re-activate only if something turned them off
    parent_ids = [state["campaigns"][k][f] for k in CAMPAIGNS for f in ("campaign_id", "adset_id")]
    infos = get_many(api, parent_ids, "id,name,status,effective_status")
    for pid in parent_ids:
        info = infos.get(pid) or {}
        rec = {"id": pid, "name": info.get("name"), "status": info.get("status"), "effective_status": info.get("effective_status")}
        if info.get("status") != "ACTIVE":
            try:
                api.graph("POST", pid, data={"status": "ACTIVE"})
                chk = get_many(api, [pid], "status,effective_status").get(pid) or {}
                rec.update({"status": chk.get("status"), "effective_status": chk.get("effective_status"), "reactivated": True})
                log(f"statics_activate: parent {pid} was {info.get('status')} -> {chk.get('status')}")
            except Exception as exc:
                add_error(state, stage="statics_activate", object=pid, error=str(exc)[:400])
        act["parents"].append(rec)
    save_state(state)
    activated = 0
    for rec in wave_ads(state, STATICS_BATCH):
        eff = rec.get("effective_status")
        if is_blocked(rec) or eff in PENDING_STATES:
            act["not_activated"].append({"campaign": rec["campaign"], "name": rec["name"], "ad_id": rec["ad_id"], "effective_status": eff,
                                         "issues_info": rec.get("issues_info"), "ad_review_feedback": rec.get("ad_review_feedback")})
            log(f"statics_activate: SKIP {rec['campaign']}/{rec['name']}: {eff} {json.dumps(rec.get('ad_review_feedback') or rec.get('issues_info') or '', ensure_ascii=False)[:200]}")
            continue
        if rec.get("status") == "ACTIVE":
            activated += 1; continue
        try:
            api.graph("POST", rec["ad_id"], data={"status": "ACTIVE"})
            chk = get_many(api, [rec["ad_id"]], "status,effective_status").get(rec["ad_id"]) or {}
            rec["status"] = chk.get("status"); rec["effective_status"] = chk.get("effective_status"); rec["activated_utc"] = now_utc()
            if chk.get("status") == "ACTIVE":
                activated += 1
                log(f"statics_activate: {rec['campaign']}/{rec['name']} -> ACTIVE [{chk.get('effective_status')}]")
            else:
                add_error(state, stage="statics_activate", campaign=rec["campaign"], name=rec["name"], ad_id=rec["ad_id"], error=f"status after POST = {chk.get('status')}")
            save_state(state)
            time.sleep(0.5)
        except Exception as exc:
            add_error(state, stage="statics_activate", campaign=rec["campaign"], name=rec["name"], ad_id=rec["ad_id"], error=str(exc)[:500])
            log(f"statics_activate: {rec['campaign']}/{rec['name']} ERROR {exc}")
    act["activated_ads"] = activated
    act["done"] = True
    act["done_utc"] = now_utc()
    save_state(state)
    mark_phase(state, "statics_activate", f"{activated} ads ACTIVE, {len(act['not_activated'])} not activated")
    log(f"statics_activate: done — {activated} ads ACTIVE, {len(act['not_activated'])} not activated")


def phase_statics_readback(api: Api, state: dict) -> None:
    """Readback strictly via ?ids= (the /ads listing edge may be throttled), then registry append."""
    blk = statics_block(state)
    ads = wave_ads(state, STATICS_BATCH)
    infos = get_many(api, [a["ad_id"] for a in ads], "id,name,status,effective_status,creative{id}")
    for rec in ads:
        info = infos.get(rec["ad_id"]) or {}
        rec["status"] = info.get("status", rec.get("status")); rec["effective_status"] = info.get("effective_status", rec.get("effective_status"))
    parent_ids = [state["campaigns"][k][f] for k in CAMPAIGNS for f in ("campaign_id", "adset_id")]
    parents = get_many(api, parent_ids, "id,name,status,effective_status")  # mixed campaign+adset batch: common fields only
    rb: dict = {"ts": now_utc(), "parents": parents, "ads": {}}
    for key in CAMPAIGNS:
        mine = [a for a in ads if a["campaign"] == key]
        dist: dict[str, int] = {}
        for a in mine:
            dist[a.get("effective_status")] = dist.get(a.get("effective_status"), 0) + 1
        rb["ads"][key] = {"count": len(mine), "distribution": dist, "items": [{"name": a["name"], "ad_id": a["ad_id"], "status": a.get("status"), "effective_status": a.get("effective_status")} for a in mine]}
        c = state["campaigns"][key]
        log(f"statics_readback: {key}: campaign {parents.get(c['campaign_id'], {}).get('status')}/{parents.get(c['campaign_id'], {}).get('effective_status')} | "
            f"adset {parents.get(c['adset_id'], {}).get('status')}/{parents.get(c['adset_id'], {}).get('effective_status')} | statics ads {len(mine)} {dist}")
    blk["readback"] = rb
    save_state(state)
    sync_registry(state)
    blk["registry_appended"] = True
    save_state(state)
    mark_phase(state, "statics_readback", "ok")


# ----------------------------------------------------------------------------
def phase_status(state: dict) -> None:
    print(f"batch {state['batch']} | forms {[(fl, f.get('id')) for fl, f in state['forms'].items()]} | wave-1 ads {len(wave_ads(state, BATCH))}/{len(ad_plan())} | total ads {len(state['ads'])} | errors {len(state['errors'])}")
    print(f"{'campaign':34} {'campaign_id':20} {'adset_id':20} {'budget':>7} {'ads':>4} {'active':>6} {'pending':>7} {'blocked':>7} status")
    for key, spec in CAMPAIGNS.items():
        c = state["campaigns"].get(key, {})
        mine = [a for a in state["ads"] if a["campaign"] == key]
        active = sum(1 for a in mine if a.get("status") == "ACTIVE")
        pending = sum(1 for a in mine if a.get("effective_status") in PENDING_STATES)
        blocked = sum(1 for a in mine if is_blocked(a))
        print(f"{spec['name']:34} {str(c.get('campaign_id')):20} {str(c.get('adset_id')):20} {spec['daily_budget']:>7} {len(mine):>4} {active:>6} {pending:>7} {blocked:>7} "
              f"camp {c.get('campaign_status')} | adset {c.get('adset_status')}")
    print("videos:", {f: (r.get('video_id'), r.get('status'), r.get('source')) for f, r in state['uploads']['videos'].items()})
    print("review:", state["review"].get("distribution"), "| activation:", state["activation"].get("done"), state["activation"].get("activated_ads"))
    if state.get("statics"):
        blk = state["statics"]
        print(f"statics wave ({STATICS_BATCH}): ads {len(wave_ads(state, STATICS_BATCH))}/{len(statics_plan())} | images {len(blk['uploads']['images'])} | videos {[(f, r.get('video_id'), r.get('status')) for f, r in blk['uploads']['videos'].items()]}")
        for key in CAMPAIGNS:
            mine = [a for a in wave_ads(state, STATICS_BATCH) if a["campaign"] == key]
            print(f"   {key}: {len(mine)} ads | active {sum(1 for a in mine if a.get('status') == 'ACTIVE')} | pending {sum(1 for a in mine if a.get('effective_status') in PENDING_STATES)} | blocked {sum(1 for a in mine if is_blocked(a))}")
        print("   review:", blk["review"].get("distribution"), "| activation:", blk["activation"].get("done"), blk["activation"].get("activated_ads"), "| not activated:", len(blk["activation"].get("not_activated", [])))
    for e in state["errors"]:
        print("ERROR:", json.dumps(e, ensure_ascii=False)[:300])
    for n in state["activation"].get("not_activated", []):
        print("NOT ACTIVATED:", json.dumps(n, ensure_ascii=False)[:300])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["form", "upload", "build", "review", "readback", "statics", "statics_review", "statics_readback", "status"])
    ap.add_argument("--budget-sec", type=int, default=560)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    DEADLINE[0] = time.time() + args.budget_sec
    state = load_state()
    if args.phase == "status":
        phase_status(state); return
    api = Api()
    assert api.account == EXPECTED_ACCOUNT, f"account mismatch: {api.account}"
    assert api.page_id == "723322257538609", f"page mismatch: {api.page_id}"
    log(f"phase '{args.phase}' start: token {mask(api.token)}, api {api.version}, account {api.account}, budget {args.budget_sec}s")
    {
        "form": lambda: phase_form(api, state),
        "upload": lambda: phase_upload(api, state, args.workers),
        "build": lambda: phase_build(api, state),
        "review": lambda: phase_review(api, state),
        "readback": lambda: phase_readback(api, state),
        "statics": lambda: phase_statics(api, state),
        "statics_review": lambda: phase_statics_review(api, state),
        "statics_readback": lambda: phase_statics_readback(api, state),
    }[args.phase]()
    save_state(state)
    log(f"phase '{args.phase}' finished; state at {STATE_PATH}")


if __name__ == "__main__":
    main()
