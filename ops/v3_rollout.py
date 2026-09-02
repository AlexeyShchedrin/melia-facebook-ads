"""price-video-v3 rollout into live Meta campaigns — everything born PAUSED.

Usage:
  python ops/v3_rollout.py probe          # read-only: slots, donors, idempotency
  python ops/v3_rollout.py upload         # upload needed videos/images (resume-safe)
  python ops/v3_rollout.py build          # create creatives+ads PAUSED, update registries
  python ops/v3_rollout.py all            # probe -> upload -> build

State/artifact: ops/v3_rollout.json (resume-safe, written after every step).
Registry append: ops/build_result.json gets new ads with "batch": "v3-2026-07-28".

Hard rules honoured:
- every ad created with status=PAUSED; no campaign/adset mutations, no resume calls
- idempotency by ad name within the adset (live check right before create)
- fresh video thumbnail fetched immediately before each video creative create
- backoff on rate-limit codes 17/613/80004 (common.py)
- ME adset: 50-ad ceiling — fill only free slots, priority SR > RU > EN
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Api, mask  # noqa: E402

OPS = Path(__file__).resolve().parent
STATE_PATH = OPS / "v3_rollout.json"
REGISTRY_PATH = OPS / "build_result.json"
ASSETS = Path(r"C:\Users\avshc\OneDrive\Desktop\Melia Reels\Price Video V3")

BATCH = "v3-2026-07-28"
EXPECTED_ACCOUNT = "act_776404808314031"
ADSET_AD_CEILING = 50

# fmt -> filename suffix
SUFFIX = {"VID916": "9x16.mp4", "VID45": "4x5.mp4", "IMG45": "IMG45.png"}

# campaign name -> (campaign_id, adset_id) — from ops/build_result.json registry
CAMPAIGNS = {
    "MB_LEADS_ME_MIX_202607": ("120250397417770233", "120250397504440233"),
    "MB_LEADS_SR_MIX_202607": ("120250397204950233", "120250397397660233"),
    "MB_LEADS_DE_MIX_202607": ("120250397116900233", "120250397193830233"),
    "MB_LEADS_PL_MIX_202607": ("120250397098510233", "120250397100510233"),
    "MB_LEADS_DE_MIX_20260707": ("120250543084620233", "120250543084900233"),
    "MB_LEADS_TR_MIX_202607": ("120250707886890233", "120250707887280233"),
    "MB_LEADS_UA_MIX_202607": ("120250708215740233", "120250708221320233"),
    "MB_RTG_B_MIX_202607": ("120250397535350233", "120250397641210233"),
    "MB_RTG_A_MIX_202607": ("120251109198470233", "120251109198870233"),
}


def lang_scheme(lang: str) -> list[tuple[str, str, str]]:
    return [
        (lang, "hook-a", "VID916"),
        (lang, "hook-b", "VID916"),
        (lang, "hook-c", "VID916"),
        (lang, "hook-a", "VID45"),
    ]


# campaign -> ordered list of (lang, hook, fmt); ME order = fill priority
PLAN: dict[str, list[tuple[str, str, str]]] = {
    "MB_LEADS_ME_MIX_202607": [
        ("SR", "hook-a", "VID916"),
        ("RU", "hook-a", "VID916"),
        ("EN", "hook-a", "VID916"),
    ],
    "MB_LEADS_SR_MIX_202607": lang_scheme("SR"),
    "MB_LEADS_DE_MIX_202607": lang_scheme("DE"),
    "MB_LEADS_PL_MIX_202607": lang_scheme("PL"),
    "MB_LEADS_DE_MIX_20260707": lang_scheme("DE"),
    "MB_LEADS_TR_MIX_202607": lang_scheme("TR"),
    "MB_LEADS_UA_MIX_202607": lang_scheme("UA"),
    "MB_RTG_B_MIX_202607": [
        ("SR", "hook-a", "IMG45"),
        ("RU", "hook-a", "IMG45"),
        ("EN", "hook-a", "IMG45"),
    ],
    "MB_RTG_A_MIX_202607": [
        ("DE", "hook-a", "IMG45"),
        ("PL", "hook-a", "IMG45"),
    ],
}


def ad_name(lang: str, hook: str, fmt: str) -> str:
    return f"INVEST_price-video-v3_{hook}_{fmt}_{lang}_V1"


def file_for(lang: str, hook: str, fmt: str) -> Path:
    return ASSETS / f"PriceVideoV3_{lang}_{hook}_{SUFFIX[fmt]}"


# ----------------------------------------------------------------------------
def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "batch": BATCH,
        "created_utc": now_utc(),
        "account": EXPECTED_ACCOUNT,
        "api_version": None,
        "probe": {},
        "donors": {},
        "uploads": {"videos": {}, "images": {}},
        "ads": [],
        "skipped": [],
        "errors": [],
        "registry_appended": False,
    }


def save_state(state: dict) -> None:
    state["updated_utc"] = now_utc()
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------
def live_adset_ads(api: Api, adset_id: str) -> list[dict]:
    """All non-deleted ads of the adset (paused/active/archived flagged)."""
    return api.get_all(f"{adset_id}/ads", {"fields": "id,name,status,effective_status,created_time"})


def pick_donor(ads: list[dict], lang: str) -> dict | None:
    alive = [a for a in ads if a.get("effective_status") not in ("DELETED", "ARCHIVED")]
    for exact in (
        f"INVEST_price-video_kinetic_VID916_{lang}_V2",
        f"INVEST_price-video_kinetic_VID916_{lang}_V1",
    ):
        for a in alive:
            if a["name"] == exact:
                return a
    for a in alive:  # any kinetic price-video of the language
        if "INVEST_price-video_kinetic" in a["name"] and f"_{lang}_" in a["name"]:
            return a
    for a in alive:  # last resort: any ad of the language (ME/RTG mixed campaigns)
        if f"_{lang}_V" in a["name"]:
            return a
    return None


def donor_spec(api: Api, ad_id: str) -> dict:
    ad = api.graph("GET", ad_id, {"fields": "creative{id},name"})
    creative_id = ad["creative"]["id"]
    cr = api.graph("GET", creative_id, {"fields": "object_story_spec,degrees_of_freedom_spec"})
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
        "instagram_user_id": oss.get("instagram_user_id") or oss.get("instagram_actor_id"),
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
        ads = live_adset_ads(api, adset_id)
        names = {a["name"] for a in ads}
        non_archived = [a for a in ads if a.get("effective_status") != "ARCHIVED"]
        planned = PLAN[camp]
        existing_v3 = [ad_name(*p) for p in planned if ad_name(*p) in names]
        langs = sorted({p[0] for p in planned})
        donors = {}
        for lg in langs:
            d = pick_donor(ads, lg)
            donors[lg] = {"ad_id": d["id"], "name": d["name"]} if d else None
        entry = {
            "campaign_id": camp_id,
            "adset_id": adset_id,
            "live_ads": len(non_archived),
            "free_slots": ADSET_AD_CEILING - len(non_archived),
            "existing_v3": existing_v3,
            "donors": donors,
        }
        probe["campaigns"][camp] = entry
        log(
            f"probe: {camp}: {len(non_archived)} live ads, "
            f"free {entry['free_slots']}, v3 already present: {len(existing_v3)}, "
            f"donors: {', '.join(f'{k}={v['name'] if v else 'MISSING'}' for k, v in donors.items())}"
        )
    state["probe"] = probe
    save_state(state)

    # resolve donor specs (copy/form/identity) once per (campaign, lang)
    for camp, entry in probe["campaigns"].items():
        for lg, d in entry["donors"].items():
            key = f"{camp}|{lg}"
            if d is None:
                state["donors"][key] = None
                continue
            if key in state["donors"] and state["donors"][key]:
                continue
            spec = donor_spec(api, d["ad_id"])
            missing = [k for k in ("page_id", "instagram_user_id", "title", "message", "lead_gen_form_id") if not spec.get(k)]
            if missing:
                log(f"probe: WARNING {key} donor {d['name']} lacks {missing}")
            state["donors"][key] = spec
            log(
                f"probe: donor {key}: form {spec['lead_gen_form_id']}, ig {spec['instagram_user_id']}, "
                f"title '{(spec['title'] or '')[:40]}'"
            )
            save_state(state)
    save_state(state)
    log("probe: done")


# ----------------------------------------------------------------------------
def todo_for_campaign(camp: str, probe_entry: dict, state: dict) -> tuple[list[tuple[str, str, str]], list[dict]]:
    """Planned items minus already-existing; ME capped by free slots."""
    planned = PLAN[camp]
    existing = set(probe_entry["existing_v3"])
    done_in_state = {a["name"] for a in state["ads"] if a["campaign"] == camp}
    todo, skipped = [], []
    budget = None
    if camp == "MB_LEADS_ME_MIX_202607":
        budget = max(0, probe_entry["free_slots"])
    for item in planned:
        name = ad_name(*item)
        if name in existing or name in done_in_state:
            skipped.append({"campaign": camp, "name": name, "reason": "already exists in adset"})
            continue
        if budget is not None and len(todo) >= budget:
            skipped.append({"campaign": camp, "name": name, "reason": "ME at 50-ad cap (paused ads count)"})
            continue
        todo.append(item)
    return todo, skipped


def needed_files(state: dict) -> tuple[set[tuple[str, str, str]], list[dict]]:
    """Union of (lang, hook, fmt) across all campaign todos."""
    need: set[tuple[str, str, str]] = set()
    all_skips: list[dict] = []
    for camp in CAMPAIGNS:
        todo, skipped = todo_for_campaign(camp, state["probe"]["campaigns"][camp], state)
        all_skips.extend(skipped)
        need.update(todo)
    return need, all_skips


def phase_upload(api: Api, state: dict) -> None:
    if not state.get("probe"):
        raise SystemExit("run probe first")
    need, _ = needed_files(state)
    vids = sorted({(l, h, f) for (l, h, f) in need if f != "IMG45"})
    imgs = sorted({(l, h, f) for (l, h, f) in need if f == "IMG45"})
    # unique files (ME shares SR hook-a 916 with SR campaign, DE shared with DE-AT)
    vfiles = sorted({file_for(*v).name: file_for(*v) for v in vids}.items())
    ifiles = sorted({file_for(*i).name: file_for(*i) for i in imgs}.items())
    log(f"upload: {len(vfiles)} unique videos, {len(ifiles)} unique images needed")

    for fname, path in ifiles:
        if state["uploads"]["images"].get(fname, {}).get("hash"):
            log(f"upload: image {fname} already uploaded, skip")
            continue
        assert path.exists(), f"missing asset {path}"
        log(f"upload: image {fname} ({path.stat().st_size // 1024} KB)")
        with open(path, "rb") as fh:
            resp = api.graph("POST", f"{api.account}/adimages", files={"filename": (fname, fh)})
        images = resp.get("images", {})
        info = images.get(fname) or next(iter(images.values()), {})
        assert info.get("hash"), f"no hash in adimages response for {fname}"
        state["uploads"]["images"][fname] = {"hash": info["hash"], "ts": now_utc()}
        save_state(state)
        log(f"upload: image {fname} -> hash {info['hash']}")
        time.sleep(1.0)

    for fname, path in vfiles:
        rec = state["uploads"]["videos"].get(fname, {})
        if rec.get("video_id") and rec.get("status") == "ready":
            log(f"upload: video {fname} already ready ({rec['video_id']}), skip")
            continue
        if not rec.get("video_id"):
            assert path.exists(), f"missing asset {path}"
            log(f"upload: video {fname} ({path.stat().st_size // (1024 * 1024)} MB)")
            with open(path, "rb") as fh:
                resp = api.graph(
                    "POST",
                    f"{api.account}/advideos",
                    data={"name": fname},
                    files={"source": (fname, fh, "video/mp4")},
                    timeout=900,
                )
            rec = {"video_id": resp["id"], "status": "uploaded", "ts": now_utc()}
            state["uploads"]["videos"][fname] = rec
            save_state(state)
            log(f"upload: video {fname} -> id {rec['video_id']}")
        time.sleep(1.0)

    # wait for processing
    pending = {f: r for f, r in state["uploads"]["videos"].items() if r.get("status") != "ready"}
    deadline = time.time() + 30 * 60
    while pending and time.time() < deadline:
        for fname, rec in list(pending.items()):
            v = api.graph("GET", rec["video_id"], {"fields": "status"})
            vs = (v.get("status") or {}).get("video_status")
            if vs == "ready":
                rec["status"] = "ready"
                state["uploads"]["videos"][fname] = rec
                save_state(state)
                log(f"upload: video {fname} ready")
                pending.pop(fname)
            elif vs == "error":
                rec["status"] = "error"
                save_state(state)
                log(f"upload: video {fname} PROCESSING ERROR")
                state["errors"].append({"stage": "video_processing", "file": fname, "video_id": rec["video_id"]})
                save_state(state)
                pending.pop(fname)
            time.sleep(2)
        if pending:
            log(f"upload: waiting for {len(pending)} videos to process...")
            time.sleep(15)
    if pending:
        raise SystemExit(f"videos still processing after 30 min: {sorted(pending)}")
    log("upload: done")


# ----------------------------------------------------------------------------
def fresh_thumbnail(api: Api, video_id: str) -> str:
    """Fetch a fresh (non-expired) thumbnail URI right before creative create."""
    for _ in range(12):
        thumbs = api.get_all(f"{video_id}/thumbnails", {"fields": "uri,is_preferred"})
        if thumbs:
            pref = next((t for t in thumbs if t.get("is_preferred")), thumbs[0])
            return pref["uri"]
        time.sleep(10)
    raise RuntimeError(f"no thumbnails for video {video_id} after 2 min")


def build_creative(api: Api, camp: str, item: tuple[str, str, str], donor: dict, state: dict) -> str:
    lang, hook, fmt = item
    name = ad_name(lang, hook, fmt)
    cta = {"type": "SIGN_UP", "value": {"lead_gen_form_id": donor["lead_gen_form_id"]}}
    oss: dict = {"page_id": donor["page_id"]}
    if donor.get("instagram_user_id"):
        oss["instagram_user_id"] = donor["instagram_user_id"]
    if fmt == "IMG45":
        fname = file_for(lang, hook, fmt).name
        img = state["uploads"]["images"][fname]
        oss["link_data"] = {
            "image_hash": img["hash"],
            "name": donor["title"],
            "message": donor["message"],
            "link": "https://fb.me/",
            "call_to_action": cta,
        }
    else:
        fname = file_for(lang, hook, fmt).name
        vid = state["uploads"]["videos"][fname]["video_id"]
        thumb = fresh_thumbnail(api, vid)  # fresh, immediately before create
        oss["video_data"] = {
            "video_id": vid,
            "image_url": thumb,
            "title": donor["title"],
            "message": donor["message"],
            "call_to_action": cta,
        }
    data = {"name": name, "object_story_spec": json.dumps(oss)}
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
    canary_done = {"video": False, "image": False}
    total_created = 0
    state["skipped"] = []

    for camp, (camp_id, adset_id) in CAMPAIGNS.items():
        # refresh live names right before creating (idempotency by ad name in adset)
        ads_live = live_adset_ads(api, adset_id)
        names_live = {a["name"] for a in ads_live}
        entry = state["probe"]["campaigns"][camp]
        entry["existing_v3"] = [ad_name(*p) for p in PLAN[camp] if ad_name(*p) in names_live]
        if camp == "MB_LEADS_ME_MIX_202607":
            non_archived = [a for a in ads_live if a.get("effective_status") != "ARCHIVED"]
            entry["live_ads"] = len(non_archived)
            entry["free_slots"] = ADSET_AD_CEILING - len(non_archived)
        todo, skipped = todo_for_campaign(camp, entry, state)
        state["skipped"].extend(skipped)
        save_state(state)
        if not todo:
            log(f"build: {camp}: nothing to do")
            continue
        log(f"build: {camp}: creating {len(todo)} ads")
        for item in todo:
            lang, hook, fmt = item
            name = ad_name(*item)
            donor = state["donors"].get(f"{camp}|{lang}")
            if not donor:
                state["errors"].append({"stage": "build", "campaign": camp, "name": name, "error": "no donor"})
                save_state(state)
                log(f"build: {camp}/{name}: NO DONOR, skip")
                continue
            kind = "image" if fmt == "IMG45" else "video"
            try:
                creative_id = build_creative(api, camp, item, donor, state)
                validate = not canary_done[kind]
                ad_id = create_ad(api, adset_id, name, creative_id, validate_first=validate)
                check = api.graph("GET", ad_id, {"fields": "status,effective_status"})
                assert check.get("status") == "PAUSED", f"ad {ad_id} status={check.get('status')}"
                canary_done[kind] = True
                rec = {
                    "campaign": camp,
                    "campaign_id": camp_id,
                    "adset_id": adset_id,
                    "name": name,
                    "ad_id": ad_id,
                    "creative_id": creative_id,
                    "type": kind,
                    "lang": lang,
                    "hook": hook,
                    "fmt": fmt,
                    "status": check.get("status"),
                    "effective_status": check.get("effective_status"),
                    "batch": BATCH,
                    "ts": now_utc(),
                }
                state["ads"].append(rec)
                save_state(state)
                total_created += 1
                log(f"build: {camp}/{name}: ad {ad_id} (creative {creative_id}) PAUSED")
                time.sleep(1.5)
            except Exception as exc:  # keep batch going, capture item error
                state["errors"].append({"stage": "build", "campaign": camp, "name": name, "error": str(exc)[:500]})
                save_state(state)
                log(f"build: {camp}/{name}: ERROR {exc}")
                if not canary_done[kind]:
                    raise SystemExit(f"canary {kind} item failed — aborting batch: {exc}")
    log(f"build: created {total_created} ads total")
    append_registry(state)


def append_registry(state: dict) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in registry["campaigns"]}
    added = 0
    for rec in state["ads"]:
        camp = by_name.get(rec["campaign"])
        if camp is None:
            continue
        if any(a.get("ad_id") == rec["ad_id"] for a in camp["ads"]):
            continue
        camp["ads"].append(
            {
                "name": rec["name"],
                "ad_id": rec["ad_id"],
                "creative_id": rec["creative_id"],
                "type": rec["type"],
                "status": "PAUSED",
                "batch": BATCH,
            }
        )
        if "counts" in camp:
            camp["counts"][rec["type"]] = camp["counts"].get(rec["type"], 0) + 1
            camp["counts"]["total"] = camp["counts"].get("total", 0) + 1
        added += 1
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state["registry_appended"] = True
    save_state(state)
    log(f"registry: appended {added} ads to {REGISTRY_PATH.name}")


# ----------------------------------------------------------------------------
def phase_review(api: Api, state: dict, max_minutes: int = 25) -> None:
    """Poll new ads until none are PENDING_REVIEW / IN_PROCESS. Read-only, never activates."""
    ads = state.get("ads", [])
    if not ads:
        log("review: no ads in state")
        return
    deadline = time.time() + max_minutes * 60
    while True:
        dist: dict[str, int] = {}
        pending = 0
        for rec in ads:
            info = api.graph("GET", rec["ad_id"], {"fields": "status,effective_status,ad_review_feedback"})
            eff = info.get("effective_status")
            rec["status"] = info.get("status")
            rec["effective_status"] = eff
            fb = info.get("ad_review_feedback")
            if fb:
                rec["ad_review_feedback"] = fb
            dist[eff] = dist.get(eff, 0) + 1
            if eff in ("PENDING_REVIEW", "IN_PROCESS"):
                pending += 1
            time.sleep(0.3)
        state["review_distribution"] = dist
        save_state(state)
        log(f"review: distribution {dist}")
        if pending == 0:
            log("review: pool clean (no PENDING_REVIEW / IN_PROCESS)")
            break
        if time.time() > deadline:
            log(f"review: {pending} ads still in review after {max_minutes} min — reporting as-is")
            break
        log(f"review: {pending} ads still in review, next poll in 120s")
        time.sleep(120)


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "probe"
    api = Api()
    state = load_state()
    if phase in ("probe", "all"):
        phase_probe(api, state)
    if phase in ("upload", "all"):
        phase_upload(api, state)
    if phase in ("build", "all"):
        phase_build(api, state)
    if phase in ("review", "all"):
        phase_review(api, state)
    log(f"phase '{phase}' complete; state at {STATE_PATH}")


if __name__ == "__main__":
    main()
