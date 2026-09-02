"""WAVE-3 full rollout — total creative-layer restart across the 9 live Meliá Budva campaigns.

Usage (every phase is resume-safe; state/artifact written after every step):
  python ops/w3_full_rollout.py probe      # read-only: live ads, slots, donors (copy/form/IG identity)
  python ops/w3_full_rollout.py delete     # ME only: DELETE the 2 dead ads listed in w3_rollout_inputs.json
  python ops/w3_full_rollout.py upload     # upload videos (poll ready) + images (hash); cached per file
  python ops/w3_full_rollout.py build      # creatives + ads, ALL born PAUSED; idempotent by ad name in adset
  python ops/w3_full_rollout.py review     # poll review every 3 min (90 min max); when clean -> ACTIVATE all
  python ops/w3_full_rollout.py pause_old  # ONLY after activation: pause tired pre-2026-07-15 ads
  python ops/w3_full_rollout.py status     # summary table

Options:
  --budget-sec N   stop cleanly (state saved) before N seconds elapsed; re-run to continue (default 540)
  --workers N      parallel video uploads (default 3)

Artifact: ops/w3_full_rollout.json  {"ads":[...], "deleted":[...], "paused":[...], "uploads":{...}, "errors":[...]}
Registry: ops/build_result.json gets the new ads with "batch": "w3-2026-09-01".
Token is never printed (common.mask).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GRAPH, Api, mask  # noqa: E402

OPS = Path(__file__).resolve().parent
STATE_PATH = OPS / "w3_full_rollout.json"
LOG_PATH = OPS / "w3_full_rollout.log"
REGISTRY_PATH = OPS / "build_result.json"
INPUTS_PATH = OPS / "w3_rollout_inputs.json"
ASSETS = Path(r"C:\Users\avshc\OneDrive\Desktop\Melia Reels\Wave 3")

BATCH = "w3-2026-09-01"
EXPECTED_ACCOUNT = "act_776404808314031"
ADSET_AD_CEILING = 50
OLD_CUTOFF = "2026-07-15"  # created_time date < this => "old"
KEEP_SUBSTRINGS = ("dawn-to-lights", "price-video_kinetic", "operator-trust", "price-video-v3", "_V3", "_W3")
REVIEW_POLL_SEC = 180
UPLOAD_DEFAULT_RATE = 80_000  # bytes/sec per stream, conservative (observed 80-130 KB/s with 4 workers)
REVIEW_MAX_MIN = 90
PENDING_STATES = ("PENDING_REVIEW", "IN_PROCESS")
BLOCKED_STATES = ("DISAPPROVED", "WITH_ISSUES")

# campaign name -> (campaign_id, adset_id) — from ops/build_result.json registry (verified 2026-09-02)
CAMPAIGNS: dict[str, tuple[str, str]] = {
    "MB_LEADS_SR_MIX_202607": ("120250397204950233", "120250397397660233"),
    "MB_LEADS_DE_MIX_202607": ("120250397116900233", "120250397193830233"),
    "MB_LEADS_DE_MIX_20260707": ("120250543084620233", "120250543084900233"),
    "MB_LEADS_PL_MIX_202607": ("120250397098510233", "120250397100510233"),
    "MB_LEADS_TR_MIX_202607": ("120250707886890233", "120250707887280233"),
    "MB_LEADS_UA_MIX_202607": ("120250708215740233", "120250708221320233"),
    "MB_LEADS_ME_MIX_202607": ("120250397417770233", "120250397504440233"),
    "MB_RTG_B_MIX_202607": ("120250397535350233", "120250397641210233"),
    "MB_RTG_A_MIX_202607": ("120251109198470233", "120251109198870233"),
}
ME = "MB_LEADS_ME_MIX_202607"

# concept -> (folder, ad-name prefix)
CONCEPTS: dict[str, tuple[str, str]] = {
    "01": ("01-seasons-alive", "SEASONS_w3-seasons-alive_four-seasons"),
    "02": ("02-price-math-2", "INVEST_w3-price-math-2_rent-vs-down"),
    "03": ("03-keys-2027", "TURNKEY_w3-keys-2027_site-footage"),
    "04": ("04-owner-morning", "FIRSTLINE_w3-owner-morning_pov-price"),
    "card2": ("05-static-facts", "TURNKEY_w3-card2-timeline_static"),
    "card3": ("05-static-facts", "MELIAHOME_w3-card3-melia_static"),
    "card4": ("05-static-facts", "INVEST_w3-card4-sqm_static"),
    "card6": ("05-static-facts", "FIRSTLINE_w3-card6-inventory_static"),
}
VIDEO_SUFFIX = {"VID916": "9x16.mp4", "VID45": "4x5.mp4"}

Item = tuple[str, str, str]  # (lang, concept, fmt)


def full_set(lang: str) -> list[Item]:
    return [
        (lang, "01", "VID916"), (lang, "01", "VID45"),
        (lang, "02", "VID916"), (lang, "02", "VID45"),
        (lang, "03", "VID916"), (lang, "03", "VID45"),
        (lang, "04", "VID916"),
        (lang, "card2", "IMG45"), (lang, "card3", "IMG45"), (lang, "card4", "IMG45"),
    ]


def rtg_b_set(lang: str) -> list[Item]:
    return [(lang, "card2", "IMG45"), (lang, "card3", "IMG45"), (lang, "card6", "IMG45"), (lang, "03", "VID916")]


def rtg_a_set(lang: str) -> list[Item]:
    return rtg_b_set(lang) + [(lang, "02", "VID916")]


# campaign -> ordered items; ME order = fill priority for the free slots
PLAN: dict[str, list[Item]] = {
    "MB_LEADS_SR_MIX_202607": full_set("SR"),
    "MB_LEADS_DE_MIX_202607": full_set("DE"),
    "MB_LEADS_DE_MIX_20260707": full_set("DE"),
    "MB_LEADS_PL_MIX_202607": full_set("PL"),
    "MB_LEADS_TR_MIX_202607": full_set("TR"),
    "MB_LEADS_UA_MIX_202607": full_set("UA"),
    ME: [("SR", "01", "VID916"), ("SR", "02", "VID916"), ("SR", "03", "VID916"), ("RU", "02", "VID916"), ("RU", "03", "VID916")],
    "MB_RTG_B_MIX_202607": rtg_b_set("SR") + rtg_b_set("RU"),
    "MB_RTG_A_MIX_202607": rtg_a_set("DE") + rtg_a_set("PL"),
}


def ad_name(lang: str, concept: str, fmt: str) -> str:
    return f"{CONCEPTS[concept][1]}_{fmt}_{lang}_W3"


def file_for(lang: str, concept: str, fmt: str) -> Path:
    folder, _ = CONCEPTS[concept]
    base = ASSETS if lang == "EN" else ASSETS / lang
    if fmt in VIDEO_SUFFIX:
        return base / folder / f"W3-{concept}_{lang}_{VIDEO_SUFFIX[fmt]}"
    return base / folder / f"W3-05_{concept}_{lang}_{fmt}.png"


def kind_of(fmt: str) -> str:
    return "video" if fmt in VIDEO_SUFFIX else "image"


# ----------------------------------------------------------------------------
DEADLINE = [float("inf")]
PACE = [5.0]  # seconds between ad creations (ad-account rate limit: code 17 / subcode 2446079)
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
        "phase_log": [],
        "probe": {},
        "donors": {},
        "deleted": [],
        "uploads": {"videos": {}, "images": {}},
        "ads": [],
        "skipped": [],
        "errors": [],
        "review": {"started_utc": None, "polls": [], "distribution": {}, "clean": False},
        "activation": {"done": False, "done_utc": None, "activated": 0, "not_activated": []},
        "paused": [],
        "pause_old": {"done": False, "per_campaign": {}},
        "registry_appended": False,
    }


def save_state(state: dict) -> None:
    with _state_lock:
        state["updated_utc"] = now_utc()
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)


def mark_phase(state: dict, phase: str, note: str) -> None:
    state["phase_log"].append({"phase": phase, "ts": now_utc(), "note": note})
    save_state(state)


def add_error(state: dict, **rec) -> None:
    rec["ts"] = now_utc()
    state["errors"].append(rec)
    save_state(state)


# ----------------------------------------------------------------------------
def live_adset_ads(api: Api, adset_id: str) -> list[dict]:
    """All ads of the adset that are not deleted/archived (paused ones included — they count towards the 50 cap)."""
    ads = api.get_all(f"{adset_id}/ads", {"fields": "id,name,status,effective_status,created_time"})
    return [a for a in ads if a.get("effective_status") not in ("DELETED", "ARCHIVED") and a.get("status") != "DELETED"]


def try_list_ads(api: Api, adset_id: str) -> list[dict] | None:
    """Single-shot paged /ads listing WITHOUT backoff; None when the edge is throttled (code 17 etc.)."""
    out: list[dict] = []
    after = None
    while True:
        params = {"fields": "id,name,status,effective_status,created_time", "limit": 200, "access_token": api.token}
        if after:
            params["after"] = after
        r = api.session.get(f"{GRAPH}/{api.version}/{adset_id}/ads", params=params, timeout=120)
        if r.status_code != 200:
            try:
                err = r.json().get("error", {})
            except Exception:
                err = {}
            if err.get("code") in (4, 17, 613, 80004, 80005) or r.status_code == 429:
                return None
            raise RuntimeError(f"list ads {adset_id} failed: {json.dumps({k: err.get(k) for k in ('message', 'code', 'error_subcode')})}")
        chunk = r.json()
        out.extend(chunk.get("data", []))
        after = chunk.get("paging", {}).get("cursors", {}).get("after")
        if not after or not chunk.get("paging", {}).get("next"):
            break
    return [a for a in out if a.get("effective_status") not in ("DELETED", "ARCHIVED") and a.get("status") != "DELETED"]


def get_many(api: Api, ids: list[str], fields: str) -> dict[str, dict]:
    """Batched GET via ?ids= (50 per call) — rate-limit friendly polling."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        resp = api.graph("GET", "", {"ids": ",".join(chunk), "fields": fields})
        out.update(resp)
    return out


def pick_donor(ads: list[dict], lang: str) -> dict | None:
    alive = [a for a in ads if not a["name"].endswith("_W3")]
    alive.sort(key=lambda a: 0 if a.get("status") == "ACTIVE" else 1)  # prefer running ads
    for exact in (
        f"INVEST_price-video_kinetic_VID916_{lang}_V2",
        f"INVEST_price-video_kinetic_VID916_{lang}_V1",
    ):
        for a in alive:
            if a["name"] == exact:
                return a
    for a in alive:  # any price-video of the language (kinetic / v3)
        if "price-video" in a["name"] and f"_{lang}_" in a["name"]:
            return a
    for a in alive:  # last resort: any ad of the language
        if f"_{lang}_" in a["name"]:
            return a
    return None


def donor_spec(api: Api, ad_id: str) -> dict:
    ad = api.graph("GET", ad_id, {"fields": "creative{id},name"})
    creative_id = ad["creative"]["id"]
    cr = api.graph("GET", creative_id, {"fields": "object_story_spec,degrees_of_freedom_spec,instagram_user_id"})
    oss = cr.get("object_story_spec", {})
    vd = oss.get("video_data", {})
    ld = oss.get("link_data", {})
    title = vd.get("title") or ld.get("name")
    message = vd.get("message") or ld.get("message")
    cta = vd.get("call_to_action") or ld.get("call_to_action") or {}
    form_id = (cta.get("value") or {}).get("lead_gen_form_id")
    return {
        "donor_ad_id": ad_id,
        "donor_ad_name": ad.get("name"),
        "donor_creative_id": creative_id,
        "page_id": oss.get("page_id"),
        "instagram_user_id": oss.get("instagram_user_id") or oss.get("instagram_actor_id") or cr.get("instagram_user_id"),
        "title": title,
        "message": message,
        "lead_gen_form_id": form_id,
        "degrees_of_freedom_spec": cr.get("degrees_of_freedom_spec"),
    }


# ----------------------------------------------------------------------------
def phase_probe(api: Api, state: dict) -> None:
    log(f"probe: token {mask(api.token)}, api {api.version}, account {api.account}")
    assert api.account == EXPECTED_ACCOUNT, f"account mismatch: {api.account}"
    acct = api.graph("GET", api.account, {"fields": "name,account_status"})
    log(f"probe: account ok -> {acct.get('name')} (status {acct.get('account_status')})")
    state["api_version"] = api.version

    probe: dict = {"ts": now_utc(), "campaigns": {}}
    for camp, (camp_id, adset_id) in CAMPAIGNS.items():
        cinfo = api.graph("GET", camp_id, {"fields": "name,status,effective_status"})
        ainfo = api.graph("GET", adset_id, {"fields": "name,status,effective_status,campaign_id"})
        assert cinfo["name"] == camp, f"campaign name mismatch {camp_id}: {cinfo['name']}"
        assert ainfo["campaign_id"] == camp_id, f"adset {adset_id} not in campaign {camp_id}"
        ads = live_adset_ads(api, adset_id)
        names = {a["name"] for a in ads}
        planned = PLAN[camp]
        existing_w3 = [ad_name(*p) for p in planned if ad_name(*p) in names]
        langs = sorted({p[0] for p in planned})
        donors = {}
        for lg in langs:
            d = pick_donor(ads, lg)
            donors[lg] = {"ad_id": d["id"], "name": d["name"]} if d else None
        old_active = [
            a for a in ads
            if a.get("status") == "ACTIVE" and a["created_time"][:10] < OLD_CUTOFF
            and not any(k in a["name"] for k in KEEP_SUBSTRINGS)
        ]
        entry = {
            "campaign_id": camp_id,
            "adset_id": adset_id,
            "campaign_status": f"{cinfo.get('status')}/{cinfo.get('effective_status')}",
            "adset_status": f"{ainfo.get('status')}/{ainfo.get('effective_status')}",
            "live_ads": len(ads),
            "active_ads": sum(1 for a in ads if a.get("status") == "ACTIVE"),
            "free_slots": ADSET_AD_CEILING - len(ads),
            "planned": len(planned),
            "existing_w3": existing_w3,
            "donors": donors,
            "old_active_to_pause_preview": len(old_active),
        }
        probe["campaigns"][camp] = entry
        log(
            f"probe: {camp}: camp {entry['campaign_status']} adset {entry['adset_status']} | "
            f"{entry['live_ads']} live ({entry['active_ads']} active), free {entry['free_slots']}, planned {len(planned)}, "
            f"W3 already present {len(existing_w3)}, old-active-to-pause {len(old_active)} | "
            f"donors: {', '.join(f'{k}={v['name'] if v else 'MISSING'}' for k, v in donors.items())}"
        )
    state["probe"] = probe
    save_state(state)

    for camp, entry in probe["campaigns"].items():
        for lg, d in entry["donors"].items():
            key = f"{camp}|{lg}"
            if d is None:
                state["donors"][key] = None
                log(f"probe: WARNING no donor for {key}")
                continue
            cur = state["donors"].get(key)
            if cur and cur.get("donor_ad_id") == d["ad_id"]:
                continue
            spec = donor_spec(api, d["ad_id"])
            missing = [k for k in ("page_id", "instagram_user_id", "title", "message", "lead_gen_form_id") if not spec.get(k)]
            if missing:
                log(f"probe: WARNING {key} donor {d['name']} lacks {missing}")
            state["donors"][key] = spec
            log(f"probe: donor {key}: form {spec['lead_gen_form_id']}, ig {spec['instagram_user_id']}, title '{(spec['title'] or '')[:40]}'")
            save_state(state)
    mark_phase(state, "probe", "ok")
    log("probe: done")


# ----------------------------------------------------------------------------
def phase_delete(api: Api, state: dict) -> None:
    inputs = json.loads(INPUTS_PATH.read_text(encoding="utf-8"))
    me_adset = CAMPAIGNS[ME][1]
    for d in inputs["me_delete"]:
        prev = next((x for x in state["deleted"] if x["ad_id"] == d["id"]), None)
        if prev and prev.get("verified"):
            log(f"delete: {d['name']} ({d['id']}) already deleted+verified, skip")
            continue
        try:
            cur = api.graph("GET", d["id"], {"fields": "name,status,effective_status,adset_id"})
        except RuntimeError as exc:
            log(f"delete: GET {d['id']} failed ({str(exc)[:160]}) — treating as already gone")
            state["deleted"].append({"ad_id": d["id"], "name": d["name"], "campaign": ME, "verified": True, "note": "GET failed before delete", "ts": now_utc()})
            save_state(state)
            continue
        assert cur.get("adset_id") == me_adset, f"{d['id']} is not in ME adset ({cur.get('adset_id')})"
        assert cur.get("name") == d["name"], f"{d['id']} name mismatch: {cur.get('name')}"
        if cur.get("status") == "DELETED" or cur.get("effective_status") == "DELETED":
            log(f"delete: {d['name']} already DELETED")
            state["deleted"].append({"ad_id": d["id"], "name": d["name"], "campaign": ME, "verified": True, "note": "was already deleted", "ts": now_utc()})
            save_state(state)
            continue
        resp = api.graph("DELETE", d["id"])
        log(f"delete: DELETE {d['name']} ({d['id']}) -> {resp}")
        verified, note = False, ""
        try:
            chk = api.graph("GET", d["id"], {"fields": "status,effective_status"})
            verified = chk.get("status") == "DELETED" or chk.get("effective_status") == "DELETED"
            note = f"post-delete GET: status={chk.get('status')} effective={chk.get('effective_status')}"
        except RuntimeError as exc:
            verified = True
            note = f"post-delete GET errored (object gone): {str(exc)[:160]}"
        log(f"delete: verify {d['id']}: {note} -> verified={verified}")
        state["deleted"].append({
            "ad_id": d["id"], "name": d["name"], "campaign": ME, "spend_eur": d.get("spend"),
            "response": resp, "verified": verified, "note": note, "ts": now_utc(),
        })
        save_state(state)
        if not verified:
            add_error(state, stage="delete", ad_id=d["id"], name=d["name"], error=note)
    mark_phase(state, "delete", f"{sum(1 for x in state['deleted'] if x.get('verified'))} verified")
    log("delete: done")


# ----------------------------------------------------------------------------
def todo_for_campaign(camp: str, existing_names: set[str], state: dict, free_slots: int | None) -> tuple[list[Item], list[dict]]:
    done_in_state = {a["name"] for a in state["ads"] if a["campaign"] == camp}
    todo, skipped = [], []
    for item in PLAN[camp]:
        name = ad_name(*item)
        if name in existing_names or name in done_in_state:
            skipped.append({"campaign": camp, "name": name, "reason": "already exists in adset"})
            continue
        if free_slots is not None and len(todo) >= free_slots:
            skipped.append({"campaign": camp, "name": name, "reason": f"adset at {ADSET_AD_CEILING}-ad cap (paused ads count)"})
            continue
        todo.append(item)
    return todo, skipped


def needed_files(state: dict) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]]]:
    need: set[Item] = set()
    for camp in CAMPAIGNS:
        entry = state["probe"]["campaigns"][camp]
        existing = set(entry["existing_w3"])
        free = entry["free_slots"] if camp == ME else None
        todo, _ = todo_for_campaign(camp, existing, state, free)
        need.update(todo)
    vids = {file_for(*i).name: file_for(*i) for i in need if kind_of(i[2]) == "video"}
    imgs = {file_for(*i).name: file_for(*i) for i in need if kind_of(i[2]) == "image"}
    return sorted(vids.items()), sorted(imgs.items())


def upload_one_video(fname: str, path: Path, state: dict) -> None:
    api = Api()  # own session per worker
    with open(path, "rb") as fh:
        resp = api.graph(
            "POST", f"{api.account}/advideos",
            data={"name": fname},
            files={"source": (fname, fh, "video/mp4")},
            timeout=900,
        )
    with _state_lock:
        state["uploads"]["videos"][fname] = {"video_id": resp["id"], "status": "uploaded", "size_mb": round(path.stat().st_size / 1048576, 1), "ts": now_utc()}
    save_state(state)
    log(f"upload: video {fname} -> id {resp['id']}")


def phase_upload(api: Api, state: dict, workers: int) -> None:
    if not state.get("probe"):
        raise SystemExit("run probe first")
    vfiles, ifiles = needed_files(state)
    log(f"upload: {len(vfiles)} unique videos, {len(ifiles)} unique images needed")
    for fname, path in ifiles + vfiles:
        assert path.exists(), f"missing asset {path}"

    for fname, path in ifiles:
        if state["uploads"]["images"].get(fname, {}).get("hash"):
            continue
        if out_of_budget():
            log("upload: budget exhausted — re-run to continue"); return
        log(f"upload: image {fname} ({path.stat().st_size // 1024} KB)")
        with open(path, "rb") as fh:
            resp = api.graph("POST", f"{api.account}/adimages", files={"filename": (fname, fh)})
        images = resp.get("images", {})
        info = images.get(fname) or next(iter(images.values()), {})
        assert info.get("hash"), f"no hash in adimages response for {fname}"
        state["uploads"]["images"][fname] = {"hash": info["hash"], "ts": now_utc()}
        save_state(state)
        log(f"upload: image {fname} -> hash {info['hash']}")
        time.sleep(0.5)

    pending_up = [(f, p) for f, p in vfiles if not state["uploads"]["videos"].get(f, {}).get("video_id")]
    if pending_up:
        log(f"upload: {len(pending_up)} videos to upload with {workers} workers")
        # largest first; a worker only takes a file whose estimated transfer fits the remaining budget
        queue = sorted(pending_up, key=lambda fp: fp[1].stat().st_size, reverse=True)
        rates: list[float] = []  # measured bytes/sec per completed file in this run
        qlock = threading.Lock()

        def pick() -> tuple[str, Path] | None:
            with qlock:
                remaining = DEADLINE[0] - time.time()
                rate = min(rates) if rates else UPLOAD_DEFAULT_RATE
                for i, (f, p) in enumerate(queue):
                    if p.stat().st_size / rate * 1.15 <= remaining:
                        return queue.pop(i)
                return None

        def worker() -> None:
            while True:
                item = pick()
                if item is None:
                    return
                f, p = item
                t0 = time.time()
                try:
                    upload_one_video(f, p, state)
                    with qlock:
                        rates.append(p.stat().st_size / max(1.0, time.time() - t0))
                except Exception as exc:
                    log(f"upload: video {f} FAILED {str(exc)[:300]}")
                    add_error(state, stage="upload", file=f, error=str(exc)[:500])

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if queue:
            log(f"upload: {len(queue)} videos not started (budget) — re-run to continue")

    # wait for processing
    pending = {f: r for f, r in state["uploads"]["videos"].items() if r.get("video_id") and r.get("status") != "ready"}
    while pending:
        if out_of_budget():
            log(f"upload: budget exhausted while {len(pending)} videos processing — re-run to continue"); return
        infos = get_many(api, [r["video_id"] for r in pending.values()], "status")
        for fname, rec in list(pending.items()):
            vs = ((infos.get(rec["video_id"]) or {}).get("status") or {}).get("video_status")
            if vs == "ready":
                rec["status"] = "ready"; rec["ready_utc"] = now_utc()
                state["uploads"]["videos"][fname] = rec
                pending.pop(fname)
                log(f"upload: video {fname} ready")
            elif vs == "error":
                rec["status"] = "error"
                state["uploads"]["videos"][fname] = rec
                pending.pop(fname)
                log(f"upload: video {fname} PROCESSING ERROR")
                add_error(state, stage="video_processing", file=fname, video_id=rec["video_id"], error="video_status=error")
        save_state(state)
        if pending:
            log(f"upload: waiting for {len(pending)} videos to process...")
            time.sleep(15)
    ready = sum(1 for r in state["uploads"]["videos"].values() if r.get("status") == "ready")
    left = [f for f, _ in vfiles if state["uploads"]["videos"].get(f, {}).get("status") != "ready"]
    if left:
        log(f"upload: {ready}/{len(vfiles)} videos ready, {len(left)} still to upload/process — re-run to continue")
        return
    mark_phase(state, "upload", f"{ready} videos ready, {len(state['uploads']['images'])} images")
    log("upload: done")


# ----------------------------------------------------------------------------
def usage_snapshot(api: Api) -> dict:
    """ads_management usage from the x-business-use-case-usage header (percentages, ETA in minutes)."""
    try:
        r = api.session.get(f"{GRAPH}/{api.version}/{api.account}", params={"fields": "id", "access_token": api.token}, timeout=60)
        entries = json.loads(r.headers.get("x-business-use-case-usage", "{}")).get(api.account.replace("act_", ""), [])
        return next((e for e in entries if e.get("type") == "ads_management"), entries[0] if entries else {})
    except Exception:
        return {}


def usage_guard(api: Api, threshold: int = 93) -> None:
    """Sleep proactively while the ad-account usage is near its ceiling (avoids code 17 escalation)."""
    for _ in range(30):
        u = usage_snapshot(api)
        if not u:
            return
        worst = max(u.get("call_count", 0), u.get("total_cputime", 0), u.get("total_time", 0))
        eta_min = u.get("estimated_time_to_regain_access", 0) or 0
        if eta_min > 0:
            wait = min(300, max(60, int(eta_min * 60)))
        elif worst >= threshold:
            wait = 60
        else:
            return
        log(f"usage: calls {u.get('call_count')}% cpu {u.get('total_cputime')}% time {u.get('total_time')}% eta {eta_min} min -> sleeping {wait}s")
        if out_of_budget():
            return
        time.sleep(wait)


def fresh_thumbnail(api: Api, video_id: str) -> str:
    """Fetch a fresh (non-expired) thumbnail URI right before the creative create call."""
    for _ in range(12):
        thumbs = api.get_all(f"{video_id}/thumbnails", {"fields": "uri,is_preferred"})
        if thumbs:
            pref = next((t for t in thumbs if t.get("is_preferred")), thumbs[0])
            return pref["uri"]
        time.sleep(10)
    raise RuntimeError(f"no thumbnails for video {video_id} after 2 min")


def build_creative(api: Api, item: Item, donor: dict, state: dict) -> str:
    lang, concept, fmt = item
    name = ad_name(*item)
    cta = {"type": "SIGN_UP", "value": {"lead_gen_form_id": donor["lead_gen_form_id"]}}
    oss: dict = {"page_id": donor["page_id"], "instagram_user_id": donor["instagram_user_id"]}
    fname = file_for(*item).name
    if kind_of(fmt) == "image":
        img = state["uploads"]["images"][fname]
        oss["link_data"] = {
            "image_hash": img["hash"],
            "name": donor["title"],
            "message": donor["message"],
            "link": "https://fb.me/",
            "call_to_action": cta,
        }
    else:
        vrec = state["uploads"]["videos"][fname]
        assert vrec.get("status") == "ready", f"video {fname} not ready"
        thumb = fresh_thumbnail(api, vrec["video_id"])  # fresh, immediately before create
        oss["video_data"] = {
            "video_id": vrec["video_id"],
            "image_url": thumb,
            "title": donor["title"],
            "message": donor["message"],
            "call_to_action": cta,
        }
    data = {"name": f"{name}_cr {BATCH}", "object_story_spec": json.dumps(oss, ensure_ascii=False)}
    if donor.get("degrees_of_freedom_spec"):
        data["degrees_of_freedom_spec"] = json.dumps(donor["degrees_of_freedom_spec"])
    resp = api.graph("POST", f"{api.account}/adcreatives", data=data)
    return resp["id"]


def create_ad(api: Api, adset_id: str, name: str, creative_id: str, validate_first: bool = False) -> str:
    data = {
        "name": name,
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": "PAUSED",
    }
    if validate_first:
        api.graph("POST", f"{api.account}/ads", data={**data, "execution_options": json.dumps(["validate_only"])})
    resp = api.graph("POST", f"{api.account}/ads", data=data)
    return resp["id"]


def phase_build(api: Api, state: dict) -> None:
    if not state.get("probe"):
        raise SystemExit("run probe first")
    canary_done = {"video": any(a["type"] == "video" for a in state["ads"]), "image": any(a["type"] == "image" for a in state["ads"])}
    total_created = 0
    state["skipped"] = [s for s in state["skipped"] if s.get("reason") != "already exists in adset"]

    for camp, (camp_id, adset_id) in CAMPAIGNS.items():
        if out_of_budget():
            log("build: budget exhausted — re-run to continue"); save_state(state); return
        # refresh live names right before creating (idempotency by ad name in adset)
        entry = state["probe"]["campaigns"][camp]
        mine_now = sum(1 for a in state["ads"] if a["campaign"] == camp)
        ads_live = try_list_ads(api, adset_id)
        if ads_live is None:
            # /ads edge throttled (code 17 / 2446079): idempotency from state + last probe, slots derived from last refresh
            drift = mine_now - entry.get("state_ads_at_refresh", 0)
            entry["free_slots"] = entry["free_slots"] - drift
            entry["state_ads_at_refresh"] = mine_now
            names_live = {}
            known = {a["name"] for a in state["ads"] if a["campaign"] == camp} | set(entry["existing_w3"])
            log(f"build: {camp}: /ads listing throttled — idempotency from state ({len(known)} known names), free slots {entry['free_slots']}")
        else:
            names_live = {a["name"]: a for a in ads_live}
            known = set(names_live)
            entry["live_ads"] = len(ads_live)
            entry["free_slots"] = ADSET_AD_CEILING - len(ads_live)
            entry["state_ads_at_refresh"] = mine_now
            entry["existing_w3"] = [ad_name(*p) for p in PLAN[camp] if ad_name(*p) in names_live]
        # adopt planned ads that already exist live but are missing from state (e.g. killed between create and save)
        for p in PLAN[camp]:
            nm = ad_name(*p)
            if nm in names_live and not any(a["name"] == nm and a["campaign"] == camp for a in state["ads"]):
                live = names_live[nm]
                info = api.graph("GET", live["id"], {"fields": "creative{id},status,effective_status"})
                state["ads"].append({
                    "campaign": camp, "campaign_id": camp_id, "adset_id": adset_id, "name": nm,
                    "ad_id": live["id"], "creative_id": (info.get("creative") or {}).get("id"),
                    "type": kind_of(p[2]), "lang": p[0], "concept": p[1], "fmt": p[2],
                    "status": info.get("status"), "effective_status": info.get("effective_status"),
                    "batch": BATCH, "ts": now_utc(), "adopted_pre_existing": True,
                })
                log(f"build: {camp}/{nm}: adopted pre-existing ad {live['id']}")
        free = entry["free_slots"] if camp == ME else None
        todo, skipped = todo_for_campaign(camp, known, state, free)
        state["skipped"] = [s for s in state["skipped"] if s["campaign"] != camp] + [s for s in skipped if s["reason"] != "already exists in adset"]
        save_state(state)
        if not todo:
            log(f"build: {camp}: nothing to do ({len(entry['existing_w3'])} planned W3 already present)")
            continue
        log(f"build: {camp}: creating {len(todo)} ads (free slots {entry['free_slots']})")
        for idx, item in enumerate(todo):
            if out_of_budget():
                log("build: budget exhausted — re-run to continue"); save_state(state); return
            if idx % 2 == 0:
                usage_guard(api)
            lang, concept, fmt = item
            name = ad_name(*item)
            donor = state["donors"].get(f"{camp}|{lang}")
            if not donor:
                add_error(state, stage="build", campaign=camp, name=name, error="no donor")
                log(f"build: {camp}/{name}: NO DONOR, skip")
                continue
            kind = kind_of(fmt)
            try:
                creative_id = build_creative(api, item, donor, state)
                validate = not canary_done[kind]
                ad_id = create_ad(api, adset_id, name, creative_id, validate_first=validate)
                if validate:  # canary only: read back and prove the ad was born PAUSED
                    check = api.graph("GET", ad_id, {"fields": "status,effective_status"})
                    assert check.get("status") == "PAUSED", f"ad {ad_id} status={check.get('status')}"
                else:  # POST carried status=PAUSED; the review poll re-reads every ad — save the call
                    check = {"status": "PAUSED", "effective_status": "IN_PROCESS"}
                canary_done[kind] = True
                state["ads"].append({
                    "campaign": camp, "campaign_id": camp_id, "adset_id": adset_id, "name": name,
                    "ad_id": ad_id, "creative_id": creative_id, "type": kind,
                    "lang": lang, "concept": concept, "fmt": fmt,
                    "status": check.get("status"), "effective_status": check.get("effective_status"),
                    "batch": BATCH, "ts": now_utc(),
                })
                save_state(state)
                total_created += 1
                log(f"build: {camp}/{name}: ad {ad_id} (creative {creative_id}) PAUSED [{check.get('effective_status')}]")
                time.sleep(PACE[0])
            except Exception as exc:
                add_error(state, stage="build", campaign=camp, name=name, error=str(exc)[:500])
                log(f"build: {camp}/{name}: ERROR {exc}")
                if not canary_done[kind]:
                    raise SystemExit(f"canary {kind} item failed — aborting batch: {exc}")
    log(f"build: created {total_created} ads this run; {len(state['ads'])} W3 ads tracked in state")
    sync_registry(state)
    mark_phase(state, "build", f"{len(state['ads'])} ads tracked")


def sync_registry(state: dict) -> None:
    """Append this batch's ads to ops/build_result.json (idempotent by ad_id) and refresh their status."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in registry["campaigns"]}
    added = updated = 0
    for rec in state["ads"]:
        camp = by_name.get(rec["campaign"])
        if camp is None:
            continue
        existing = next((a for a in camp["ads"] if a.get("ad_id") == rec["ad_id"]), None)
        if existing:
            if existing.get("status") != rec.get("status"):
                existing["status"] = rec.get("status"); updated += 1
            continue
        camp["ads"].append({
            "name": rec["name"], "ad_id": rec["ad_id"], "creative_id": rec["creative_id"],
            "type": rec["type"], "status": rec.get("status"), "batch": BATCH,
        })
        if "counts" in camp and camp["counts"]:
            camp["counts"][rec["type"]] = camp["counts"].get(rec["type"], 0) + 1
            camp["counts"]["total"] = camp["counts"].get("total", 0) + 1
        added += 1
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state["registry_appended"] = True
    save_state(state)
    log(f"registry: +{added} ads, {updated} status updates in {REGISTRY_PATH.name}")


# ----------------------------------------------------------------------------
def poll_pool(api: Api, state: dict) -> dict[str, int]:
    ads = state["ads"]
    infos = get_many(api, [a["ad_id"] for a in ads], "status,effective_status,issues_info,ad_review_feedback")
    dist: dict[str, int] = {}
    for rec in ads:
        info = infos.get(rec["ad_id"]) or {}
        rec["status"] = info.get("status", rec.get("status"))
        rec["effective_status"] = info.get("effective_status", rec.get("effective_status"))
        if info.get("issues_info"):
            rec["issues_info"] = info["issues_info"]
        if info.get("ad_review_feedback"):
            rec["ad_review_feedback"] = info["ad_review_feedback"]
        dist[rec["effective_status"]] = dist.get(rec["effective_status"], 0) + 1
    state["review"]["distribution"] = dist
    state["review"]["polls"].append({"ts": now_utc(), "distribution": dist})
    save_state(state)
    return dist


def phase_review(api: Api, state: dict) -> None:
    if not state["ads"]:
        log("review: no ads in state"); return
    if state["activation"]["done"]:
        log("review: activation already done"); return
    rv = state["review"]
    if not rv["started_utc"]:
        rv["started_utc"] = now_utc(); save_state(state)
    started = datetime.strptime(rv["started_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    while True:
        dist = poll_pool(api, state)
        pending = sum(dist.get(s, 0) for s in PENDING_STATES)
        elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60
        log(f"review: {dist} | pending {pending} | {elapsed_min:.0f} min since start")
        if pending == 0:
            rv["clean"] = True; save_state(state)
            log("review: pool clean (no PENDING_REVIEW / IN_PROCESS) -> activating")
            break
        if elapsed_min >= REVIEW_MAX_MIN:
            log(f"review: {pending} ads still in review after {REVIEW_MAX_MIN} min -> activating the approved ones, reporting the rest")
            break
        if time.time() + REVIEW_POLL_SEC > DEADLINE[0]:
            log("review: invocation budget reached — re-run to keep polling"); return
        time.sleep(REVIEW_POLL_SEC)
    activate_all(api, state)


def activate_all(api: Api, state: dict) -> None:
    act = state["activation"]
    act["not_activated"] = []
    activated = 0
    for rec in state["ads"]:
        eff = rec.get("effective_status")
        if rec.get("status") == "ACTIVE":
            activated += 1
            continue
        if eff in BLOCKED_STATES or eff in PENDING_STATES:
            act["not_activated"].append({
                "campaign": rec["campaign"], "name": rec["name"], "ad_id": rec["ad_id"],
                "effective_status": eff, "issues_info": rec.get("issues_info"), "ad_review_feedback": rec.get("ad_review_feedback"),
            })
            log(f"activate: SKIP {rec['campaign']}/{rec['name']}: {eff} {json.dumps(rec.get('issues_info') or rec.get('ad_review_feedback') or '', ensure_ascii=False)[:200]}")
            continue
        if out_of_budget():
            log("activate: budget exhausted — re-run review to finish activation"); save_state(state); return
        try:
            api.graph("POST", rec["ad_id"], data={"status": "ACTIVE"})
            rec["status"] = "ACTIVE"
            rec["activated_utc"] = now_utc()
            save_state(state)
            log(f"activate: {rec['campaign']}/{rec['name']} -> POST status=ACTIVE ok")
            time.sleep(0.5)
        except Exception as exc:
            add_error(state, stage="activate", campaign=rec["campaign"], name=rec["name"], ad_id=rec["ad_id"], error=str(exc)[:500])
            log(f"activate: {rec['campaign']}/{rec['name']} ERROR {exc}")
    # verify every ad with batched reads (2 calls for 83 ads instead of 83 GETs)
    infos = get_many(api, [a["ad_id"] for a in state["ads"]], "status,effective_status")
    activated = 0
    for rec in state["ads"]:
        info = infos.get(rec["ad_id"]) or {}
        rec["status"] = info.get("status", rec.get("status"))
        rec["effective_status"] = info.get("effective_status", rec.get("effective_status"))
        if rec["status"] == "ACTIVE":
            activated += 1
        elif not any(n["ad_id"] == rec["ad_id"] for n in act["not_activated"]):
            add_error(state, stage="activate", campaign=rec["campaign"], name=rec["name"], ad_id=rec["ad_id"], error=f"status after activation = {rec['status']}")
    log(f"activate: verified via batch read: {activated} ACTIVE")
    act["activated"] = activated
    act["done"] = True
    act["done_utc"] = now_utc()
    save_state(state)
    sync_registry(state)
    mark_phase(state, "activate", f"{activated} active, {len(act['not_activated'])} not activated")
    log(f"activate: done — {activated} ACTIVE, {len(act['not_activated'])} not activated")


# ----------------------------------------------------------------------------
def campaign_ads_from_registry(api: Api, camp: str, adset_id: str) -> list[dict]:
    """Adset ads via registry ids + batched ?ids= reads — works while the /ads listing edge is throttled."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    entry = next((c for c in registry["campaigns"] if c["name"] == camp), None)
    ids = [a["ad_id"] for a in (entry or {}).get("ads", []) if a.get("ad_id")]
    extra_path = OPS / "w3_en_rtgb.json"
    if camp == "MB_RTG_B_MIX_202607" and extra_path.exists():
        ids += [a["ad_id"] for a in json.loads(extra_path.read_text(encoding="utf-8"))]
    infos = get_many(api, sorted(set(ids)), "name,status,effective_status,created_time,adset_id")
    ads = [{"id": k, **v} for k, v in infos.items() if isinstance(v, dict)]
    return [
        a for a in ads
        if a.get("adset_id") == adset_id
        and a.get("effective_status") not in ("DELETED", "ARCHIVED") and a.get("status") != "DELETED"
    ]


def phase_pause_old(api: Api, state: dict) -> None:
    if not state["activation"]["done"]:
        raise SystemExit("pause_old refused: new ads are not activated yet (run review first)")
    already = {p["ad_id"] for p in state["paused"]}
    for camp, (camp_id, adset_id) in CAMPAIGNS.items():
        per = state["pause_old"]["per_campaign"].setdefault(camp, {})
        if per.get("done"):
            continue
        ads = try_list_ads(api, adset_id)
        source = "live /ads"
        if ads is None:
            ads = campaign_ads_from_registry(api, camp, adset_id)
            source = "registry ids"
            log(f"pause_old: {camp}: /ads listing throttled — using registry ids ({len(ads)} ads)")
        per["source"] = source
        candidates = [
            a for a in ads
            if a.get("status") == "ACTIVE"
            and a["created_time"][:10] < OLD_CUTOFF
            and not any(k in a["name"] for k in KEEP_SUBSTRINGS)
        ]
        kept_old = [a for a in ads if a.get("status") == "ACTIVE" and a["created_time"][:10] < OLD_CUTOFF and any(k in a["name"] for k in KEEP_SUBSTRINGS)]
        per.update({"active_before": sum(1 for a in ads if a.get("status") == "ACTIVE"), "candidates": len(candidates), "kept_old_active": len(kept_old)})
        save_state(state)
        log(f"pause_old: {camp}: {per['active_before']} active, {len(candidates)} old to pause, {len(kept_old)} old kept (champions)")
        posted: list[dict] = []
        for a in candidates:
            if a["id"] in already:
                continue
            if out_of_budget():
                log("pause_old: budget exhausted — re-run to continue"); save_state(state); return
            try:
                api.graph("POST", a["id"], data={"status": "PAUSED"})
                state["paused"].append({"campaign": camp, "name": a["name"], "ad_id": a["id"], "created_time": a["created_time"], "verified": False, "ts": now_utc()})
                already.add(a["id"])
                posted.append(a)
                save_state(state)
                log(f"pause_old: {camp}/{a['name']} ({a['created_time'][:10]}) -> POST status=PAUSED ok")
                time.sleep(0.4)
            except Exception as exc:
                add_error(state, stage="pause_old", campaign=camp, name=a["name"], ad_id=a["id"], error=str(exc)[:500])
                log(f"pause_old: {camp}/{a['name']} ERROR {exc}")
        # verify this campaign's pauses with batched reads
        to_verify = [p for p in state["paused"] if p["campaign"] == camp and not p.get("verified")]
        if to_verify:
            infos = get_many(api, [p["ad_id"] for p in to_verify], "status")
            for p in to_verify:
                st = (infos.get(p["ad_id"]) or {}).get("status")
                p["verified"] = st == "PAUSED"
                if not p["verified"]:
                    add_error(state, stage="pause_old", campaign=camp, name=p["name"], ad_id=p["ad_id"], error=f"status after POST = {st}")
            save_state(state)
            log(f"pause_old: {camp}: verified {sum(1 for p in to_verify if p['verified'])}/{len(to_verify)} paused")
        per["paused_now"] = sum(1 for p in state["paused"] if p["campaign"] == camp and p.get("verified"))
        per["active_after"] = per["active_before"] - sum(1 for p in state["paused"] if p["campaign"] == camp and p.get("verified") and p["ad_id"] in {a["id"] for a in candidates})
        per["done"] = True
        save_state(state)
        log(f"pause_old: {camp}: active after = {per['active_after']}")
    state["pause_old"]["done"] = all(v.get("done") for v in state["pause_old"]["per_campaign"].values()) and len(state["pause_old"]["per_campaign"]) == len(CAMPAIGNS)
    save_state(state)
    mark_phase(state, "pause_old", f"{len(state['paused'])} paused")
    log(f"pause_old: done — {len(state['paused'])} ads paused")


# ----------------------------------------------------------------------------
def phase_status(state: dict) -> None:
    print(f"batch {state['batch']} | ads {len(state['ads'])} | deleted {len(state['deleted'])} | paused {len(state['paused'])} | errors {len(state['errors'])}")
    print(f"{'campaign':28} {'planned':>7} {'created':>7} {'active':>6} {'blocked':>7} {'paused_old':>10}")
    for camp in CAMPAIGNS:
        mine = [a for a in state["ads"] if a["campaign"] == camp]
        active = sum(1 for a in mine if a.get("status") == "ACTIVE")
        blocked = sum(1 for a in mine if a.get("effective_status") in BLOCKED_STATES)
        paused_old = sum(1 for p in state["paused"] if p["campaign"] == camp)
        print(f"{camp:28} {len(PLAN[camp]):>7} {len(mine):>7} {active:>6} {blocked:>7} {paused_old:>10}")
    print("review:", state["review"].get("distribution"), "| activation:", state["activation"].get("done"), "| pause_old:", state["pause_old"].get("done"))
    for e in state["errors"]:
        print("ERROR:", json.dumps(e, ensure_ascii=False)[:300])
    for s in state["skipped"]:
        print("SKIP:", json.dumps(s, ensure_ascii=False)[:200])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["probe", "delete", "upload", "build", "review", "pause_old", "status"])
    ap.add_argument("--budget-sec", type=int, default=540)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pace-sec", type=float, default=5.0)
    args = ap.parse_args()
    DEADLINE[0] = time.time() + args.budget_sec
    PACE[0] = args.pace_sec
    state = load_state()
    if args.phase == "status":
        phase_status(state); return
    api = Api()
    assert api.account == EXPECTED_ACCOUNT, f"account mismatch: {api.account}"
    {
        "probe": lambda: phase_probe(api, state),
        "delete": lambda: phase_delete(api, state),
        "upload": lambda: phase_upload(api, state, args.workers),
        "build": lambda: phase_build(api, state),
        "review": lambda: phase_review(api, state),
        "pause_old": lambda: phase_pause_old(api, state),
    }[args.phase]()
    log(f"phase '{args.phase}' finished; state at {STATE_PATH}")


if __name__ == "__main__":
    main()
