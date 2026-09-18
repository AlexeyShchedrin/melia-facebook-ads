"""Wave 4 (ALL creatives, "use everything now") on act_776404808314031 — everything born PAUSED.

Phases (each resume-safe; ops/w4_rollout_2026-09-17.json rewritten after every object):
  python ops/w4_wave_all.py probe     # account / usage tier / page-token mint / page forms / donor adsets / campaigns (read-only)
  python ops/w4_wave_all.py forms     # 10 Instant Forms (Page token): LF_<LANG>_W4-DEFAULT_v1_202609 + LF_<LANG>_W4-INSTALMENT_v1_202609
  python ops/w4_wave_all.py adsets    # 10 NEW ad sets PAUSED, targeting/DSA copied from the donor ad set of the same campaign
  python ops/w4_wave_all.py media     # 272 videos + 261 images (statics + carousel cards); is_ai_generated probes on v26.0
  python ops/w4_wave_all.py build     # 393 ads PAUSED: VID916 -> IMG45 -> CAR45 -> VID45 per ad set; canaries via validate_only
  python ops/w4_wave_all.py readback  # ?ids= readback of ads / adsets / forms, registry append (batch w4-2026-09-17-ALL)
  python ops/w4_wave_all.py status    # offline summary

Nothing is activated, nothing deleted, no budget of an existing object is touched.
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
from common import GRAPH, Api, mask  # noqa: E402

OPS = Path(__file__).resolve().parent
STATE_PATH = OPS / "w4_rollout_2026-09-17.json"
LOG_PATH = OPS / "w4_rollout_2026-09-17.log"
REGISTRY_PATH = OPS / "build_result.json"
PLAN_PATH = OPS / "w4_wave_all_now.json"
STEP1_PATH = OPS / "w4_wave_a_step1.json"
FORM_TEMPLATE_PATH = OPS / "w4_form_v1_questions.json"
DOF_DONOR_PATH = OPS / "ips_dubai.json"

BATCH = "w4-2026-09-17-ALL"
EXPECTED_ACCOUNT = "act_776404808314031"
EXPECTED_PAGE = "723322257538609"
IG_USER_ID = "17841475384506205"
LINK = "https://meliabudva.com"
PRIVACY_URL = "https://kvadra.me/privacy"
ADSET_AD_CEILING = 50
AI_PROBE_VERSION = "v26.0"
USAGE_PAUSE_AT = 90  # percent of any ads_management usage counter
TRANSCODE_DIR = Path("C:/Users/avshc/AppData/Local/Temp/claude/C--Users-avshc-kvadra-workspace/bdf8818a-afa8-4cd8-aaf1-b640dab8f00c/scratchpad/w4_transcode")
TRANSCODE_MANIFEST = TRANSCODE_DIR / "manifest.json"  # written by ops/w4_transcode.py (coordinator 2026-09-17 22:40)
TRANSCODE_WAIT_SEC = 1800  # how long an upload worker waits for the transcoder before falling back to the original
FORM_LANGS = ("SR", "DE", "PL", "UA", "TR")
FORM_LOCALE = {"DE": "de_DE", "PL": "pl_PL", "TR": "tr_TR", "SR": "en_US", "UA": "en_US"}
FORBIDDEN_KEYS = {"purpose", "deal_type"}
FORMAT_ORDER = {"VID916": 0, "IMG45": 1, "CAR45": 2, "VID45": 3}
# echelons (coordinator 2026-09-17 22:26, slow uplink): 1 = VID916 + IMG45(+916) + CAR45 first, 2 = VID45 afterwards; 0 = everything
ECHELON_FORMATS = {1: {"VID916", "IMG45", "CAR45"}, 2: {"VID45"}}
FORMAT_OVERRIDE: set[str] = set()  # --formats IMG45,CAR45 narrows media/build further (takes precedence over --echelon)
PENDING_STATES = ("PENDING_REVIEW", "IN_PROCESS")

# ----------------------------------------------------------------------------------------------
# Form copy (custom question keys: budget/timing verbatim from v1 template; unit_type / instalment new)
PRIVACY_TEXT = {"DE": "Datenschutzerklärung", "PL": "Polityka prywatności", "TR": "Gizlilik Politikası",
                "SR": "Politika privatnosti", "UA": "Політика конфіденційності"}

HEADLINE = {  # [full, compact (<=60 chars)]
    "DEFAULT": {
        "DE": ["Preisliste & Zahlungsplan — 1 Schlafzimmer ab 263.200 € (Richtpreis)", "Preise & Raten — 1 Schlafzimmer ab 263.200 € (Richtpreis)"],
        "PL": ["Cennik i plan płatności — 1 sypialnia od 263 200 € (cena orientacyjna)", "Cennik i raty — 1 sypialnia od 263 200 € (cena orientacyjna)"],
        "TR": ["Fiyat listesi ve ödeme planı — 1+1 263.200 €'dan (gösterge fiyat)", "Fiyat listesi ve ödeme planı — 1+1 263.200 €'dan (gösterge)"],
        "SR": ["Cenovnik i plan plaćanja — 1-sobni od 263.200 € (indikativna cena)", "Cenovnik i rate — 1-sobni od 263.200 € (indikativna cena)"],
        "UA": ["Прайс-лист і план оплати — 1 спальня від 263 200 € (орієнтовна ціна)", "Ціни та план оплати — 1 спальня від 263 200 € (орієнтовно)"],
    },
    "INSTALMENT": {
        "DE": ["20 % jetzt · zinsfrei bis Q4 2027 — 1 Schlafzimmer ab 263.200 € (Richtpreis)", "20% jetzt · zinsfrei bis Q4 2027 — ab 263.200 € (Richtpreis)"],
        "PL": ["20% teraz · bez odsetek do IV kw. 2027 — 1 sypialnia od 263 200 € (cena orientacyjna)", "20% teraz · 0% do IV kw. 2027 — od 263 200 € (orientacyjnie)"],
        "TR": ["Şimdi %20 · 2027 Q4'e kadar faizsiz — 1+1 263.200 €'dan (gösterge fiyat)", "%20 şimdi · Q4 2027'ye dek faizsiz — 263.200€'dan (gösterge)"],
        "SR": ["20 % sada · bez kamate do Q4 2027 — 1-sobni od 263.200 € (indikativna cena)", "20% sada · 0% kamate do Q4 2027 — od 263.200 € (indikativno)"],
        "UA": ["20% зараз · без відсотків до IV кв. 2027 — 1 спальня від 263 200 € (орієнтовна ціна)", "20% зараз · 0% до IV кв. 2027 — від 263 200 € (орієнтовно)"],
    },
}

UNIT_TYPE_Q = {
    "DE": ("1 oder 2 Schlafzimmer?", ["1 Schlafzimmer", "2 Schlafzimmer", "Noch nicht sicher"]),
    "PL": ("1 czy 2 sypialnie?", ["1 sypialnia", "2 sypialnie", "Jeszcze nie wiem"]),
    "TR": ("1 yatak odası mı, 2 mi?", ["1 yatak odası", "2 yatak odası", "Henüz emin değilim"]),
    "SR": ("1 ili 2 spavaće sobe?", ["1 spavaća soba", "2 spavaće sobe", "Još nisam siguran/na"]),
    "UA": ("1 чи 2 спальні?", ["1 спальня", "2 спальні", "Ще не вирішив(-ла)"]),
}
INSTALMENT_Q = {
    "DE": ("Interesse am Ratenplan mit 20 % Anzahlung?", ["Ja", "Mehr erfahren"]),
    "PL": ("Interesuje Cię plan ratalny z wpłatą 20%?", ["Tak", "Chcę wiedzieć więcej"]),
    "TR": ("%20 peşinatlı taksit planıyla ilgileniyor musunuz?", ["Evet", "Daha fazla bilgi istiyorum"]),
    "SR": ("Zainteresovani za plan plaćanja sa 20 % učešća?", ["Da", "Recite mi više"]),
    "UA": ("Цікавить розстрочка з першим внеском 20%?", ["Так", "Розкажіть детальніше"]),
}


def form_name(lang: str, kind: str) -> str:
    return f"LF_{lang}_W4-{kind}_v1_202609"


def form_key(lang: str, kind: str) -> str:
    return f"W4_{lang}_{'default' if kind == 'DEFAULT' else 'instalment'}"


def form_specs() -> dict[str, dict]:
    tpl = json.loads(FORM_TEMPLATE_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for lang in FORM_LANGS:
        v1 = {q["key"]: q for q in tpl[lang]["questions"]}
        budget = {"type": "CUSTOM", "key": "budget", "label": v1["budget"]["label"], "options": v1["budget"]["options"]}
        timing = {"type": "CUSTOM", "key": "timing", "label": v1["timing"]["label"], "options": v1["timing"]["options"]}
        std = [{"type": "FULL_NAME", "key": "full_name"}, {"type": "PHONE", "key": "phone"}, {"type": "EMAIL", "key": "email"}]
        ul, uo = UNIT_TYPE_Q[lang]
        unit = {"type": "CUSTOM", "key": "unit_type", "label": ul, "options": [{"key": f"unit_{i + 1}", "value": v} for i, v in enumerate(uo)]}
        il, io = INSTALMENT_Q[lang]
        inst = {"type": "CUSTOM", "key": "instalment", "label": il, "options": [{"key": f"inst_{i + 1}", "value": v} for i, v in enumerate(io)]}
        for kind, custom in (("DEFAULT", [budget, timing, unit]), ("INSTALMENT", [inst, budget, timing])):
            qs = std + custom
            for q in qs:
                assert q["key"] not in FORBIDDEN_KEYS, q["key"]
            out[form_key(lang, kind)] = {
                "lang": lang, "kind": kind, "name": form_name(lang, kind), "locale": FORM_LOCALE[lang],
                "privacy": {"url": PRIVACY_URL, "link_text": PRIVACY_TEXT[lang]},
                "headlines": HEADLINE[kind][lang], "questions": qs,
            }
    return out


# ----------------------------------------------------------------------------------------------
_state_lock = threading.RLock()
_usage_lock = threading.Lock()
_usage: dict = {"snapshot": None, "ts": None}
DEADLINE = [float("inf")]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def out_of_budget() -> bool:
    return time.time() > DEADLINE[0]


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _state_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _usage_hook(resp, *args, **kwargs):  # requests response hook: free usage telemetry on every call
    raw = resp.headers.get("x-business-use-case-usage")
    if not raw:
        return
    try:
        entries = json.loads(raw).get(EXPECTED_ACCOUNT.replace("act_", ""), [])
        entry = next((e for e in entries if e.get("type") == "ads_management"), entries[0] if entries else None)
    except Exception:
        return
    if entry:
        with _usage_lock:
            _usage["snapshot"] = entry
            _usage["ts"] = time.time()


class UsageApi(Api):
    def __init__(self, version: str | None = None, token: str | None = None):
        super().__init__()
        if version:
            self.version = version
        if token:
            self.token = token
        self.session.hooks["response"].append(_usage_hook)

    def call(self, method: str, path: str, params: dict | None = None, data: dict | None = None, files: dict | None = None, timeout: int = 300) -> dict:
        """graph() with an outer 'never give up on throttling' loop (code 17 / 613 / 80004 / 2446079).

        Uploads (files=...) get a single attempt per round: re-sending a 20-35 MB body every 30-600 s while the account is
        over its time quota only burns uplink; instead we wait for the usage header's estimated_time_to_regain_access.
        """
        is_upload = files is not None
        for outer in range(24 if is_upload else 12):
            try:
                if is_upload:
                    return self.graph(method, path, params=params, data=data, files=files, timeout=timeout, max_attempts=1)
                return self.graph(method, path, params=params, data=data, files=files, timeout=timeout)
            except RuntimeError as exc:
                if "exhausted retries" in str(exc) and outer < (23 if is_upload else 11):
                    log(f"    [throttle] {method} {path}: {'upload rejected' if is_upload else 'retries exhausted'} -> waiting for quota ({outer + 1})")
                    usage_snapshot(self, refresh=True)
                    usage_guard(self)
                    time.sleep(60 if is_upload else 600)
                    continue
                raise
        raise RuntimeError("unreachable")


def usage_snapshot(api: UsageApi, refresh: bool = False) -> dict:
    with _usage_lock:
        snap, ts = _usage["snapshot"], _usage["ts"]
    if refresh or snap is None or (time.time() - (ts or 0)) > 120:
        try:
            api.session.get(f"{GRAPH}/{api.version}/{api.account}", params={"fields": "id", "access_token": api.token}, timeout=60)
        except Exception:
            pass
        with _usage_lock:
            snap = _usage["snapshot"]
    return snap or {}


def usage_worst(u: dict) -> int:
    return max(int(u.get("call_count", 0) or 0), int(u.get("total_cputime", 0) or 0), int(u.get("total_time", 0) or 0))


def usage_guard(api: UsageApi, threshold: int = USAGE_PAUSE_AT) -> None:
    """Sleep while the ads_management usage (x-business-use-case-usage) is at/over the threshold."""
    for _ in range(60):
        u = usage_snapshot(api)
        if not u:
            return
        eta_min = u.get("estimated_time_to_regain_access", 0) or 0
        worst = usage_worst(u)
        if eta_min > 0:
            wait = min(600, max(60, int(eta_min * 60)))
        elif worst >= threshold:
            wait = 90
        else:
            return
        log(f"usage: calls {u.get('call_count')}% cpu {u.get('total_cputime')}% time {u.get('total_time')}% eta {eta_min} min "
            f"(tier {u.get('ads_api_access_tier')}) -> sleeping {wait}s")
        time.sleep(wait)
        usage_snapshot(api, refresh=True)


# ----------------------------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "batch": BATCH,
        "account": EXPECTED_ACCOUNT,
        "created_utc": now_utc(),
        "api_version": None,
        "ai_probe_version": AI_PROBE_VERSION,
        "inputs": {"plan": PLAN_PATH.name, "step1_selection": STEP1_PATH.name, "form_template": FORM_TEMPLATE_PATH.name,
                   "dof_donor": f"{DOF_DONOR_PATH.name}:dof_spec"},
        "plan_change": {"ts": now_utc(), "note": "owner decision: use ALL wave-4 creatives now -> 393 ads in 10 NEW PAUSED ad sets "
                                                  "(w4_wave_all_now.json) instead of 44 ads in the old ad sets (w4_wave_a_step1.json); "
                                                  "no step-1 ads had been created on Graph before the change -> nothing to delete",
                        "old_adset_budgets_eur_applied": False},
        "phase_log": [],
        "probe": {},
        "probes": {},
        "forms": {},
        "adsets": {},
        "uploads": {"videos": {}, "images": {}},
        "ads": [],
        "skipped": [],
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
            except PermissionError:
                time.sleep(0.25)
        STATE_PATH.write_text(payload, encoding="utf-8")


def mark_phase(state: dict, phase: str, note: str) -> None:
    state["phase_log"].append({"phase": phase, "ts": now_utc(), "note": note})
    save_state(state)


def add_error(state: dict, **rec) -> None:
    rec["ts"] = now_utc()
    with _state_lock:
        state["errors"].append(rec)
        save_state(state)


def get_many(api: UsageApi, ids: list[str], fields: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        out.update(api.call("GET", "", {"ids": ",".join(chunk), "fields": fields}))
    return out


def err_text(exc: Exception) -> str:
    return str(exc)[:600]


def load_plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def ordered_ads(plan: dict, echelon: int = 0) -> list[dict]:
    """Plan order: ad sets in new_adsets order; within an ad set VID916 -> IMG45 -> CAR45 -> VID45 (stable); echelon filter by format."""
    adset_rank = {a["name"]: i for i, a in enumerate(plan["new_adsets"])}
    fmts = FORMAT_OVERRIDE or (ECHELON_FORMATS[echelon] if echelon else None)
    rows = [a for a in plan["ads"] if not fmts or a["format"] in fmts]
    return sorted(rows, key=lambda a: (adset_rank[a["adset_name"]], FORMAT_ORDER[a["format"]]))


def load_dof_spec() -> dict:
    d = json.loads(DOF_DONOR_PATH.read_text(encoding="utf-8")).get("dof_spec")
    assert d and len(d.get("creative_features_spec", {})) > 5, "donor dof_spec missing in ips_dubai.json"
    assert all(v.get("enroll_status") == "OPT_OUT" for v in d["creative_features_spec"].values()), "donor dof_spec is not all OPT_OUT"
    return d


# ----------------------------------------------------------------------------------------------
def page_token(api: UsageApi) -> str:
    r = api.call("GET", api.page_id, {"fields": "id,name,access_token"})
    assert r.get("id") == api.page_id, f"page mismatch {r.get('id')}"
    tok = r.get("access_token")
    assert tok, "no page access_token minted (system user lacks page task?)"
    log(f"page token minted for '{r.get('name')}' ({mask(tok)})")
    return tok


def phase_probe(api: UsageApi, state: dict) -> None:
    plan = load_plan()
    acc = api.call("GET", api.account, {"fields": "id,name,account_status,currency,timezone_name"})
    u = usage_snapshot(api, refresh=True)
    pt = page_token(api)
    papi = UsageApi(token=pt)
    forms = papi.get_all(f"{api.page_id}/leadgen_forms", {"fields": "id,name,status,locale,created_time"})
    w4_forms = {f["name"]: f["id"] for f in forms if f.get("name", "").startswith("LF_") and "_W4-" in f.get("name", "")}
    donors = {a["copy_targeting_from_adset"] for a in plan["new_adsets"]}
    dfields = ("id,name,campaign_id,status,effective_status,daily_budget,targeting,promoted_object,optimization_goal,billing_event,"
               "bid_strategy,destination_type,dsa_beneficiary,dsa_payor,attribution_spec,is_dynamic_creative")
    donor_info = get_many(api, sorted(donors), dfields)
    camps = sorted({a["campaign_id"] for a in plan["new_adsets"]})
    camp_info = get_many(api, camps, "id,name,status,effective_status,objective,special_ad_categories,special_ad_category_country,is_adset_budget_sharing_enabled")
    existing: dict[str, list] = {}
    for cid in camps:
        rows = api.get_all(f"{cid}/adsets", {"fields": "id,name,status,effective_status,daily_budget"})
        existing[cid] = [{k: r.get(k) for k in ("id", "name", "status", "effective_status", "daily_budget")} for r in rows
                         if r.get("effective_status") not in ("DELETED", "ARCHIVED")]
    state["probe"] = {
        "ts": now_utc(), "account": acc, "usage": u, "page_forms_total": len(forms), "page_w4_forms": w4_forms,
        "donor_adsets": donor_info, "campaigns": camp_info, "existing_adsets_per_campaign": existing,
        "plan": {"ads": len(plan["ads"]), "adsets": len(plan["new_adsets"]),
                 "per_adset": {a["name"]: a["ads"] for a in plan["new_adsets"]},
                 "unique_videos": len({a["file"] for a in plan["ads"] if a["format"] in ("VID916", "VID45")}),
                 "unique_images": len({f for a in plan["ads"] if a["format"] == "IMG45" for f in (a["file"], a.get("placement_asset_916")) if f}),
                 "unique_cards": len({c["file"] for a in plan["ads"] if a["format"] == "CAR45" for c in a["cards"]})},
    }
    state["api_version"] = api.version
    save_state(state)
    log(f"probe: account {acc.get('name')} status {acc.get('account_status')} {acc.get('currency')} | usage {u} | page forms {len(forms)} "
        f"(W4: {w4_forms}) | donors {len(donor_info)} | campaigns {[(c.get('name'), c.get('special_ad_categories')) for c in camp_info.values()]}")
    for cid, rows in existing.items():
        log(f"probe: campaign {camp_info[cid].get('name')}: {len(rows)} live adsets: {[r['name'] for r in rows]}")
    for aid, d in donor_info.items():
        log(f"probe: donor {d.get('name')} ({aid}): {d.get('optimization_goal')}/{d.get('billing_event')}/{d.get('bid_strategy')}/{d.get('destination_type')} "
            f"dsa={d.get('dsa_beneficiary')!r} targeting={json.dumps(d.get('targeting'), ensure_ascii=False)[:160]}")
    mark_phase(state, "probe", "ok")


# ----------------------------------------------------------------------------------------------
def phase_forms(api: UsageApi, state: dict) -> None:
    specs = form_specs()
    todo = [k for k in specs if not state["forms"].get(k, {}).get("id")]
    if not todo:
        log(f"forms: all {len(specs)} present — skip create")
    else:
        pt = page_token(api)
        papi = UsageApi(token=pt)
        page_forms = papi.get_all(f"{api.page_id}/leadgen_forms", {"fields": "id,name,status,locale"})
        by_name = {f.get("name"): f for f in page_forms}
        canary_done = state["probes"].get("form_validate_only") is not None
        for k in todo:
            spec = specs[k]
            usage_guard(api)
            if spec["name"] in by_name:
                f = by_name[spec["name"]]
                state["forms"][k] = {"id": f["id"], "name": spec["name"], "lang": spec["lang"], "kind": spec["kind"], "reused": True,
                                     "status": f.get("status"), "locale": f.get("locale"), "ts": now_utc()}
                save_state(state)
                log(f"forms: {k}: reusing existing {spec['name']} -> {f['id']}")
                continue
            q_keyed = [q for q in spec["questions"]]  # standard questions: type+key only (label comes from locale)
            q_bare = [q if q["type"] == "CUSTOM" else {"type": q["type"]} for q in spec["questions"]]
            base = {
                "name": spec["name"], "locale": spec["locale"],
                "privacy_policy": json.dumps(spec["privacy"], ensure_ascii=False),
                "is_optimized_for_quality": "true",
                "follow_up_action_url": LINK,
            }
            variants: list[tuple[str, dict]] = []
            for sms in ("true", "false"):
                for hl_label, hl in (("headline-full", spec["headlines"][0]), ("headline-compact", spec["headlines"][1]), ("no-headline", None)):
                    for ql, qs in (("keyed", q_keyed), ("bare", q_bare)):
                        d = {**base, "is_phone_sms_verify_enabled": sms, "questions": json.dumps(qs, ensure_ascii=False)}
                        if hl:
                            d["question_page_custom_headline"] = hl
                        variants.append((f"{spec['locale']} {'sms' if sms == 'true' else 'no-sms'} {hl_label} {ql}", d))
            if not canary_done:
                first_label, first_data = variants[0]
                try:
                    v = papi.call("POST", f"{api.page_id}/leadgen_forms", data={**first_data, "execution_options": json.dumps(["validate_only"])})
                    state["probes"]["form_validate_only"] = {"variant": first_label, "response": v, "ts": now_utc()}
                    if v.get("id"):  # the edge ignored validate_only and created the form for real -> adopt, never duplicate
                        state["forms"][k] = {"id": v["id"], "name": spec["name"], "lang": spec["lang"], "kind": spec["kind"], "reused": False,
                                             "variant": first_label, "note": "created by the validate_only canary call (edge ignored execution_options)", "ts": now_utc()}
                        state["probes"]["form_validate_only"]["note"] = "response carried an id -> form really created, adopted"
                        save_state(state)
                        log(f"forms: {k}: validate_only canary CREATED the form ({v['id']}) — adopted")
                        canary_done = True
                        continue
                    log(f"forms: validate_only canary OK on '{first_label}': {v}")
                except RuntimeError as exc:
                    state["probes"]["form_validate_only"] = {"variant": first_label, "error": err_text(exc), "ts": now_utc()}
                    log(f"forms: validate_only canary rejected: {err_text(exc)[:200]} (continuing with real creates)")
                canary_done = True
                save_state(state)
            resp = label = None
            errors = []
            for vlabel, vdata in variants:
                try:
                    resp = papi.call("POST", f"{api.page_id}/leadgen_forms", data=vdata)
                    label = vlabel
                    break
                except RuntimeError as exc:
                    errors.append({"variant": vlabel, "error": err_text(exc)})
                    log(f"forms: {k}: variant '{vlabel}' rejected: {err_text(exc)[:220]}")
            if not resp:
                add_error(state, stage="forms", form=k, error="all variants rejected", variants=errors[:6])
                continue
            state["forms"][k] = {"id": resp["id"], "name": spec["name"], "lang": spec["lang"], "kind": spec["kind"], "reused": False,
                                 "variant": label, "locale_sent": spec["locale"], "sms_verify_sent": "no-sms" not in label,
                                 "headline_sent": (spec["headlines"][0] if "headline-full" in label else spec["headlines"][1] if "headline-compact" in label else None),
                                 "rejected_variants": errors, "ts": now_utc()}
            save_state(state)
            log(f"forms: {k}: created {spec['name']} -> {resp['id']} via '{label}'")
            time.sleep(0.5)
    # readback of every form (base fields, then extended fields one group at a time)
    for k, rec in state["forms"].items():
        if not rec.get("id"):
            continue
        rb = api.call("GET", rec["id"], {"fields": "id,name,locale,status,questions,follow_up_action_url,is_optimized_for_quality,leads_count,created_time"})
        rec["readback"] = rb
        ext: dict = {}
        for fld in ("privacy_policy_url", "question_page_custom_headline", "context_card", "thank_you_page", "legal_content", "is_phone_sms_verify_enabled"):
            try:
                ext[fld] = api.call("GET", rec["id"], {"fields": fld}).get(fld)
            except RuntimeError as exc:
                ext[fld] = {"error": err_text(exc)[:200]}
        rec["readback_ext"] = ext
        keys = [q.get("key") for q in rb.get("questions", [])]
        custom = [q.get("key") for q in rb.get("questions", []) if q.get("type") == "CUSTOM"]
        expected = ["budget", "timing", "unit_type"] if rec["kind"] == "DEFAULT" else ["instalment", "budget", "timing"]
        rec["readback_ok"] = custom == expected and not (set(keys) & FORBIDDEN_KEYS)
        save_state(state)
        log(f"forms: {k}: readback {rb.get('id')} locale={rb.get('locale')} status={rb.get('status')} quality={rb.get('is_optimized_for_quality')} "
            f"headline={ext.get('question_page_custom_headline')!r} privacy={ext.get('privacy_policy_url')} custom={custom} ok={rec['readback_ok']}")
        if not rec["readback_ok"]:
            add_error(state, stage="forms_readback", form=k, error=f"custom keys {custom} != {expected}")
    have = sum(1 for k in specs if state["forms"].get(k, {}).get("id"))
    mark_phase(state, "forms", f"{have}/{len(specs)} forms present")


# ----------------------------------------------------------------------------------------------
def adset_payload(donor: dict, spec: dict, with_smart_pse: bool) -> dict:
    promoted = dict(donor.get("promoted_object") or {"page_id": EXPECTED_PAGE})
    if not with_smart_pse:
        promoted.pop("smart_pse_enabled", None)
    data = {
        "name": spec["name"], "campaign_id": spec["campaign_id"], "status": "PAUSED",
        "targeting": json.dumps(donor["targeting"], ensure_ascii=False),
        "promoted_object": json.dumps(promoted),
        "optimization_goal": donor.get("optimization_goal") or "LEAD_GENERATION",
        "billing_event": donor.get("billing_event") or "IMPRESSIONS",
        "bid_strategy": donor.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP",
        "destination_type": donor.get("destination_type") or "ON_AD",
        "daily_budget": str(int(round(spec["daily_budget_eur"] * 100))),
        "is_adset_budget_sharing_enabled": "false",
    }
    for fld in ("dsa_beneficiary", "dsa_payor"):
        if donor.get(fld):
            data[fld] = donor[fld]
    if donor.get("attribution_spec"):
        data["attribution_spec"] = json.dumps(donor["attribution_spec"])
    return data


def phase_adsets(api: UsageApi, state: dict) -> None:
    plan = load_plan()
    donors = state["probe"].get("donor_adsets") or {}
    need = {a["copy_targeting_from_adset"] for a in plan["new_adsets"]} - set(donors)
    if need:
        dfields = ("id,name,campaign_id,status,effective_status,daily_budget,targeting,promoted_object,optimization_goal,billing_event,"
                   "bid_strategy,destination_type,dsa_beneficiary,dsa_payor,attribution_spec,is_dynamic_creative")
        donors.update(get_many(api, sorted(need), dfields))
        state["probe"]["donor_adsets"] = donors
        save_state(state)
    canary_done = state["probes"].get("adset_validate_only") is not None
    for spec in plan["new_adsets"]:
        name = spec["name"]
        rec = state["adsets"].get(name)
        if rec and rec.get("id"):
            continue
        assert spec["status"] == "PAUSED", f"{name}: plan status {spec['status']} != PAUSED"
        usage_guard(api)
        live = api.get_all(f"{spec['campaign_id']}/adsets", {"fields": "id,name,status,effective_status,daily_budget"})
        hit = next((a for a in live if a.get("name") == name and a.get("effective_status") not in ("DELETED", "ARCHIVED")), None)
        base_rec = {"name": name, "slot": spec["slot"], "lang": spec["lang"], "campaign_id": spec["campaign_id"],
                    "donor_adset": spec["copy_targeting_from_adset"], "daily_budget_eur": spec["daily_budget_eur"], "planned_ads": spec["ads"]}
        if hit:
            state["adsets"][name] = {**base_rec, "id": hit["id"], "adopted_pre_existing": True, "status": hit.get("status"),
                                     "effective_status": hit.get("effective_status"), "daily_budget": hit.get("daily_budget"), "ts": now_utc()}
            save_state(state)
            log(f"adsets: {name}: adopted pre-existing {hit['id']} ({hit.get('status')}, budget {hit.get('daily_budget')})")
            continue
        donor = donors[spec["copy_targeting_from_adset"]]
        assert donor.get("campaign_id") == spec["campaign_id"], f"{name}: donor campaign {donor.get('campaign_id')} != {spec['campaign_id']}"
        variants = [("donor-promoted_object", adset_payload(donor, spec, True)), ("page_id-only promoted_object", adset_payload(donor, spec, False))]
        if not canary_done:
            ok = None
            for vlabel, vdata in variants:
                try:
                    v = api.call("POST", f"{api.account}/adsets", data={**vdata, "execution_options": json.dumps(["validate_only"])})
                    state["probes"]["adset_validate_only"] = {"adset": name, "variant": vlabel, "response": v, "ts": now_utc()}
                    ok = vlabel
                    log(f"adsets: validate_only canary OK for {name} via '{vlabel}': {v}")
                    break
                except RuntimeError as exc:
                    state["probes"]["adset_validate_only"] = {"adset": name, "variant": vlabel, "error": err_text(exc), "ts": now_utc()}
                    log(f"adsets: validate_only '{vlabel}' rejected: {err_text(exc)[:300]}")
            save_state(state)
            if ok is None:
                raise SystemExit(f"adsets: canary {name} fails to validate with every variant — aborting before any create")
            variants = [v for v in variants if v[0] == ok] + [v for v in variants if v[0] != ok]
            canary_done = True
        resp = label = None
        errors = []
        for vlabel, vdata in variants:
            try:
                resp = api.call("POST", f"{api.account}/adsets", data=vdata)
                label = vlabel
                break
            except RuntimeError as exc:
                errors.append({"variant": vlabel, "error": err_text(exc)})
                log(f"adsets: {name}: variant '{vlabel}' rejected: {err_text(exc)[:300]}")
        if not resp:
            add_error(state, stage="adsets", adset=name, error="all variants rejected", variants=errors)
            continue
        chk = get_many(api, [resp["id"]], "status,effective_status,daily_budget,name").get(resp["id"]) or {}
        assert chk.get("status") == "PAUSED", f"adset {resp['id']} status={chk.get('status')}"
        state["adsets"][name] = {**base_rec, "id": resp["id"], "variant": label, "status": chk.get("status"), "effective_status": chk.get("effective_status"),
                                 "daily_budget": chk.get("daily_budget"), "created_utc": now_utc(), "ts": now_utc()}
        save_state(state)
        log(f"adsets: {name}: created {resp['id']} PAUSED [{chk.get('effective_status')}] budget {chk.get('daily_budget')} via '{label}'")
        time.sleep(1.0)
    ids = [r["id"] for r in state["adsets"].values() if r.get("id")]
    rb = get_many(api, ids, "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,targeting,promoted_object,optimization_goal,"
                            "billing_event,bid_strategy,destination_type,dsa_beneficiary,dsa_payor,is_dynamic_creative,start_time")
    for name, rec in state["adsets"].items():
        info = rb.get(rec.get("id")) or {}
        rec["readback"] = info
        rec["status"] = info.get("status", rec.get("status"))
        rec["effective_status"] = info.get("effective_status", rec.get("effective_status"))
        expected_budget = str(int(round(rec["daily_budget_eur"] * 100)))
        rec["readback_ok"] = info.get("status") == "PAUSED" and str(info.get("daily_budget")) == expected_budget and info.get("campaign_id") == rec["campaign_id"]
        log(f"adsets: readback {name} {rec.get('id')}: {info.get('status')}/{info.get('effective_status')} budget {info.get('daily_budget')} "
            f"{info.get('optimization_goal')}/{info.get('billing_event')}/{info.get('bid_strategy')}/{info.get('destination_type')} dsa={info.get('dsa_beneficiary')!r} ok={rec['readback_ok']}")
        if not rec["readback_ok"]:
            add_error(state, stage="adsets_readback", adset=name, error=f"status={info.get('status')} budget={info.get('daily_budget')} campaign={info.get('campaign_id')}")
    save_state(state)
    mark_phase(state, "adsets", f"{len(ids)}/{len(plan['new_adsets'])} ad sets present")


# ----------------------------------------------------------------------------------------------
def media_plan(plan: dict, echelon: int = 0) -> tuple[list[tuple[str, Path, bool]], list[tuple[str, Path, bool]]]:
    """(videos, images) as (basename, path, is_ai) in plan order — first occurrence wins the AI flag."""
    videos: dict[str, tuple[Path, bool]] = {}
    images: dict[str, tuple[Path, bool]] = {}
    for a in ordered_ads(plan, echelon):
        ai = bool(a.get("is_ai_generated"))
        if a["format"] in ("VID916", "VID45"):
            p = Path(a["file"])
            videos.setdefault(p.name, (p, ai))
        elif a["format"] == "IMG45":
            for f in (a["file"], a.get("placement_asset_916")):
                if f:
                    p = Path(f)
                    images.setdefault(p.name, (p, ai))
        elif a["format"] == "CAR45":
            for c in a["cards"]:
                p = Path(c["file"])
                images.setdefault(p.name, (p, ai))
    return [(n, p, ai) for n, (p, ai) in videos.items()], [(n, p, ai) for n, (p, ai) in images.items()]


def transcode_entry(fname: str) -> dict | None:
    """Manifest entry of ops/w4_transcode.py for this basename (None until the transcoder has processed it)."""
    if not TRANSCODE_MANIFEST.exists():
        return None
    for _ in range(20):
        try:
            return json.loads(TRANSCODE_MANIFEST.read_text(encoding="utf-8")).get(fname)
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.2)
    return None


def pick_video_source(fname: str, original: Path) -> tuple[Path, dict]:
    """Wait (bounded) for the transcoder; use the transcoded file only when the manifest accepted it."""
    t0 = time.time()
    entry = transcode_entry(fname)
    while entry is None and time.time() - t0 < TRANSCODE_WAIT_SEC:
        time.sleep(15)
        entry = transcode_entry(fname)
    if entry and entry.get("ok") and Path(entry["dst"]).exists():
        return Path(entry["dst"]), {"transcoded": True, "src_size_mb": round(entry["src_size"] / 1048576, 2), "upload_size_mb": round(entry["dst_size"] / 1048576, 2),
                                   "transcode_ratio": entry.get("ratio"), "transcode_checks": entry.get("checks")}
    reason = "transcoder not finished in time" if entry is None else (entry.get("error") or f"checks failed: {entry.get('checks')}")
    return original, {"transcoded": False, "src_size_mb": round(original.stat().st_size / 1048576, 2), "upload_size_mb": round(original.stat().st_size / 1048576, 2),
                      "transcode_reason": reason}


def upload_video(api: UsageApi, state: dict, fname: str, path: Path, ai: bool, mode: str) -> dict:
    data = {"name": fname}
    ver = api.version
    if mode == "v26-flag":
        data["is_ai_generated"] = "true" if ai else "false"
        ver = AI_PROBE_VERSION
    src, tinfo = pick_video_source(fname, path)
    vapi = UsageApi(version=ver)
    t0 = time.time()
    with open(src, "rb") as fh:
        resp = vapi.call("POST", f"{api.account}/advideos", data=data, files={"source": (fname, fh, "video/mp4")}, timeout=3600)
    rec = {"video_id": resp["id"], "status": "uploaded", "size_mb": round(src.stat().st_size / 1048576, 1), "upload_sec": round(time.time() - t0),
           "is_ai_generated": ai, "ai_flag_sent": mode == "v26-flag", "api_version": ver, "uploaded_from": str(src), **tinfo, "ts": now_utc()}
    with _state_lock:
        state["uploads"]["videos"][fname] = rec
        save_state(state)
    src_note = (" transcoded from " + str(tinfo["src_size_mb"]) + " MB") if tinfo["transcoded"] else " original"
    log(f"media: video {fname} -> {resp['id']} ({rec['size_mb']} MB{src_note}, {rec['upload_sec']}s, ai={ai}, flag_sent={rec['ai_flag_sent']})")
    return rec


def upload_image(api: UsageApi, state: dict, fname: str, path: Path, ai: bool, mode: str) -> dict:
    data = {}
    ver = api.version
    if mode == "v26-flag":
        data["is_ai_generated"] = "true" if ai else "false"
        ver = AI_PROBE_VERSION
    iapi = UsageApi(version=ver)
    with open(path, "rb") as fh:
        resp = iapi.call("POST", f"{api.account}/adimages", data=data or None, files={"filename": (fname, fh, "image/png")}, timeout=600)
    images = resp.get("images", {})
    info = images.get(fname) or next(iter(images.values()), {})
    assert info.get("hash"), f"no hash in adimages response for {fname}: {json.dumps(resp)[:200]}"
    rec = {"hash": info["hash"], "size_kb": path.stat().st_size // 1024, "is_ai_generated": ai, "ai_flag_sent": mode == "v26-flag", "api_version": ver, "ts": now_utc()}
    with _state_lock:
        state["uploads"]["images"][fname] = rec
        save_state(state)
    log(f"media: image {fname} -> {info['hash']} (ai={ai}, flag_sent={rec['ai_flag_sent']})")
    return rec


def probe_ai_video(api: UsageApi, state: dict, fname: str, path: Path) -> str:
    """Upload ONE AI video through v26.0 with is_ai_generated=true; read it back with and without the field."""
    pr: dict = {"file": fname, "api_version": AI_PROBE_VERSION, "ts": now_utc()}
    vapi = UsageApi(version=AI_PROBE_VERSION)
    t0 = time.time()
    try:
        with open(path, "rb") as fh:
            resp = vapi.call("POST", f"{api.account}/advideos", data={"name": fname, "is_ai_generated": "true"}, files={"source": (fname, fh, "video/mp4")}, timeout=3600)
        pr["upload_accepted"] = True
        pr["video_id"] = resp["id"]
        state["uploads"]["videos"][fname] = {"video_id": resp["id"], "status": "uploaded", "size_mb": round(path.stat().st_size / 1048576, 1),
                                             "upload_sec": round(time.time() - t0), "is_ai_generated": True, "ai_flag_sent": True, "api_version": AI_PROBE_VERSION,
                                             "probe": True, "ts": now_utc()}
        save_state(state)
        try:
            pr["readback_with_field"] = vapi.call("GET", resp["id"], {"fields": "id,title,is_ai_generated"})
        except RuntimeError as exc:
            pr["readback_with_field"] = {"error": err_text(exc)}
        try:
            pr["readback_plain"] = vapi.call("GET", resp["id"], {})
        except RuntimeError as exc:
            pr["readback_plain"] = {"error": err_text(exc)}
        rbf = pr["readback_with_field"]
        pr["reads_back_true"] = isinstance(rbf, dict) and rbf.get("is_ai_generated") is True
        pr["decision"] = "v26-flag"
        pr["note"] = ("param accepted and reads back true" if pr["reads_back_true"] else
                      "param accepted by the upload but NOT readable (field unknown or null) -> flag still sent on every AI upload per brief; disclosure to be verified/set manually in Ads Manager")
    except RuntimeError as exc:
        pr["upload_accepted"] = False
        pr["upload_error"] = err_text(exc)
        pr["decision"] = "none"
        pr["note"] = "v26.0 upload with is_ai_generated rejected -> videos uploaded without the flag; AI disclosure manually in Ads Manager"
    state["probes"]["is_ai_generated_video"] = pr
    save_state(state)
    log(f"media: PROBE is_ai_generated on /advideos ({AI_PROBE_VERSION}): accepted={pr.get('upload_accepted')} readback={json.dumps(pr.get('readback_with_field'), ensure_ascii=False)[:200]} -> {pr['decision']}")
    return pr["decision"]


def probe_ai_image(api: UsageApi, state: dict, fname: str, path: Path) -> str:
    pr: dict = {"file": fname, "api_version": AI_PROBE_VERSION, "ts": now_utc()}
    iapi = UsageApi(version=AI_PROBE_VERSION)
    try:
        with open(path, "rb") as fh:
            resp = iapi.call("POST", f"{api.account}/adimages", data={"is_ai_generated": "true"}, files={"filename": (fname, fh, "image/png")}, timeout=600)
        images = resp.get("images", {})
        info = images.get(fname) or next(iter(images.values()), {})
        pr["upload_accepted"] = True
        pr["hash"] = info.get("hash")
        pr["upload_response"] = resp
        state["uploads"]["images"][fname] = {"hash": info["hash"], "size_kb": path.stat().st_size // 1024, "is_ai_generated": True, "ai_flag_sent": True,
                                             "api_version": AI_PROBE_VERSION, "probe": True, "ts": now_utc()}
        save_state(state)
        try:
            pr["readback_with_field"] = iapi.call("GET", f"{api.account}/adimages", {"hashes": json.dumps([info["hash"]]), "fields": "hash,name,is_ai_generated"})
        except RuntimeError as exc:
            pr["readback_with_field"] = {"error": err_text(exc)}
        try:
            pr["readback_plain"] = iapi.call("GET", f"{api.account}/adimages", {"hashes": json.dumps([info["hash"]])})
        except RuntimeError as exc:
            pr["readback_plain"] = {"error": err_text(exc)}
        rows = (pr["readback_with_field"] or {}).get("data") or []
        pr["reads_back_true"] = bool(rows) and rows[0].get("is_ai_generated") is True
        pr["decision"] = "v26-flag"
        pr["note"] = ("param accepted and reads back true" if pr["reads_back_true"] else
                      "param accepted by /adimages but NOT readable -> flag still sent on AI images; disclosure to be verified/set manually in Ads Manager")
    except RuntimeError as exc:
        pr["upload_accepted"] = False
        pr["upload_error"] = err_text(exc)
        pr["decision"] = "none"
        pr["note"] = "v26.0 /adimages with is_ai_generated rejected -> images uploaded without the flag; AI disclosure manually in Ads Manager"
    state["probes"]["is_ai_generated_image"] = pr
    save_state(state)
    log(f"media: PROBE is_ai_generated on /adimages ({AI_PROBE_VERSION}): accepted={pr.get('upload_accepted')} readback={json.dumps(pr.get('readback_with_field'), ensure_ascii=False)[:200]} -> {pr['decision']}")
    return pr["decision"]


def wait_videos_ready(api: UsageApi, state: dict) -> None:
    while True:
        pending = {f: r for f, r in state["uploads"]["videos"].items() if r.get("video_id") and r.get("status") not in ("ready", "error")}
        if not pending:
            return
        infos = get_many(api, [r["video_id"] for r in pending.values()], "status")
        for fname, rec in pending.items():
            vs = ((infos.get(rec["video_id"]) or {}).get("status") or {}).get("video_status")
            if vs == "ready":
                rec["status"] = "ready"
                rec["ready_utc"] = now_utc()
            elif vs == "error":
                rec["status"] = "error"
                add_error(state, stage="video_processing", file=fname, video_id=rec["video_id"], error="video_status=error")
        save_state(state)
        left = sum(1 for r in state["uploads"]["videos"].values() if r.get("video_id") and r.get("status") not in ("ready", "error"))
        if not left:
            return
        log(f"media: waiting for {left} videos to finish processing...")
        time.sleep(20)


def phase_media(api: UsageApi, state: dict, workers: int, echelon: int = 0) -> None:
    plan = load_plan()
    videos, images = media_plan(plan, echelon)
    for _, p, _ in videos + images:
        assert p.exists(), f"missing asset {p}"
    vids = state["uploads"]["videos"]
    imgs = state["uploads"]["images"]
    log(f"media[e{echelon}]: {len(videos)} unique videos ({sum(p.stat().st_size for _, p, _ in videos) / 1048576:.0f} MB), {len(images)} unique images; "
        f"already: {sum(1 for n, _, _ in videos if vids.get(n, {}).get('video_id'))} videos, {sum(1 for n, _, _ in images if imgs.get(n, {}).get('hash'))} images")

    # --- probes first (one AI video, one AI image), each on v26.0 with is_ai_generated=true
    if "is_ai_generated_video" not in state["probes"]:
        n, p, _ = next((v for v in videos if v[2] and not vids.get(v[0], {}).get("video_id")), videos[0])
        usage_guard(api)
        probe_ai_video(api, state, n, p)
    if "is_ai_generated_image" not in state["probes"]:
        n, p, _ = next((v for v in images if v[2] and not imgs.get(v[0], {}).get("hash")), images[0])
        usage_guard(api)
        probe_ai_image(api, state, n, p)
    vmode = state["probes"]["is_ai_generated_video"]["decision"]
    imode = state["probes"]["is_ai_generated_image"]["decision"]

    # --- one parallel queue: images first (the build canaries need hashes early), then videos; each worker has its own session.
    # The uplink is shared with OneDrive (9 connections observed 2026-09-17 22:22) -> more parallel connections = a fairer share.
    todo: list[tuple[str, str, Path, bool]] = [("image", n, p, ai) for n, p, ai in images if not imgs.get(n, {}).get("hash")]
    todo += [("video", n, p, ai) for n, p, ai in videos if not vids.get(n, {}).get("video_id")]
    log(f"media: {sum(1 for t in todo if t[0] == 'image')} images + {sum(1 for t in todo if t[0] == 'video')} videos to upload with {workers} workers "
        f"(video mode {vmode}, image mode {imode})")
    if todo:
        queue = list(todo)
        qlock = threading.Lock()
        t_start = time.time()
        done_bytes = [0]
        samples: list[tuple[float, int]] = [(t_start, 0)]  # rolling-hour speed check (note when < 0.1 MB/s for > 1 h)
        slow_noted = [0.0]

        def worker() -> None:
            wapi = UsageApi()
            while True:
                with qlock:
                    if not queue or out_of_budget():
                        return
                    kind, n, p, ai = queue.pop(0)
                usage_guard(wapi)
                try:
                    if kind == "image":
                        upload_image(wapi, state, n, p, ai, imode)
                    else:
                        upload_video(wapi, state, n, p, ai, vmode)
                    with qlock:
                        done_bytes[0] += p.stat().st_size
                        left = len(queue)
                        now = time.time()
                        rate = done_bytes[0] / 1048576 / max(1.0, now - t_start)
                        samples.append((now, done_bytes[0]))
                        old = next((sm for sm in samples if now - sm[0] >= 3600), None)
                        hour_rate = ((done_bytes[0] - old[1]) / 1048576 / (now - old[0])) if old else None
                        if hour_rate is not None and hour_rate < 0.1 and now - slow_noted[0] > 3600:
                            slow_noted[0] = now
                            state.setdefault("notes", []).append({"ts": now_utc(), "topic": "uplink-slow", "note": f"aggregate upload speed {hour_rate:.3f} MB/s over the last hour (< 0.1 MB/s); continuing, OneDrive untouched"})
                            save_state(state)
                    if left % 10 == 0:
                        log(f"media: progress — {left} files left in queue, aggregate {rate:.2f} MB/s" + (f", last hour {hour_rate:.2f} MB/s" if hour_rate is not None else ""))
                except Exception as exc:
                    add_error(state, stage=f"upload_{kind}", file=n, error=err_text(exc))
                    log(f"media: {kind} {n} FAILED {err_text(exc)[:300]}")

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if queue:
            log(f"media: {len(queue)} files not started (budget) — re-run to continue")
    wait_videos_ready(api, state)
    ready = sum(1 for n, _, _ in videos if vids.get(n, {}).get("status") == "ready")
    have_img = sum(1 for n, _, _ in images if imgs.get(n, {}).get("hash"))
    log(f"media[e{echelon}]: {ready}/{len(videos)} videos ready, {have_img}/{len(images)} images uploaded")
    if ready == len(videos) and have_img == len(images):
        mark_phase(state, f"media-e{echelon}", f"{ready} videos ready, {have_img} images")


# ----------------------------------------------------------------------------------------------
def fresh_thumbnail(api: UsageApi, video_id: str) -> str:
    for _ in range(12):
        thumbs = api.get_all(f"{video_id}/thumbnails", {"fields": "uri,is_preferred"})
        if thumbs:
            pref = next((t for t in thumbs if t.get("is_preferred")), thumbs[0])
            return pref["uri"]
        time.sleep(10)
    raise RuntimeError(f"no thumbnails for video {video_id} after 2 min")


def kind_of(fmt: str) -> str:
    return {"VID916": "video", "VID45": "video", "IMG45": "static", "CAR45": "carousel"}[fmt]


def creative_variants(api: UsageApi, state: dict, ad: dict, dof: dict, locked: str | None) -> list[tuple[str, dict]]:
    """Ordered (label, adcreative payload) variants for the ad; `locked` narrows to the variant already proven for this kind."""
    form_id = state["forms"][ad["form_key"]]["id"]
    kind = kind_of(ad["format"])
    oss_base = {"page_id": api.page_id, "instagram_user_id": IG_USER_ID}
    name = f"{ad['name']}_cr {BATCH}"
    out: list[tuple[str, dict]] = []

    def payload(oss: dict, afs: dict | None = None) -> dict:
        d = {"name": name, "object_story_spec": json.dumps(oss, ensure_ascii=False), "degrees_of_freedom_spec": json.dumps(dof)}
        if afs is not None:
            d["asset_feed_spec"] = json.dumps(afs, ensure_ascii=False)
        return d

    if kind == "video":
        vrec = state["uploads"]["videos"][Path(ad["file"]).name]
        assert vrec.get("status") == "ready", f"video {ad['file']} not ready"
        thumb = fresh_thumbnail(api, vrec["video_id"])  # fresh, right before the create call
        for cta in ("GET_QUOTE", "SIGN_UP"):
            vd = {"video_id": vrec["video_id"], "image_url": thumb, "title": ad["headline"], "message": ad["primary_text"],
                  "link_description": ad["description"], "call_to_action": {"type": cta, "value": {"lead_gen_form_id": form_id}}}
            out.append((f"video/{cta}", payload({**oss_base, "video_data": vd})))
    elif kind == "static":
        h45 = state["uploads"]["images"][Path(ad["file"]).name]["hash"]
        h916 = state["uploads"]["images"][Path(ad["placement_asset_916"]).name]["hash"]
        feed_rule = {"customization_spec": {"publisher_platforms": ["facebook", "instagram"],
                                            "facebook_positions": ["feed", "marketplace", "video_feeds", "search", "profile_feed"],
                                            "instagram_positions": ["stream", "explore", "explore_home", "profile_feed"]},
                     "image_label": {"name": "feed"}}
        story_rule = {"customization_spec": {"publisher_platforms": ["facebook", "instagram", "messenger"],
                                             "facebook_positions": ["story", "facebook_reels"], "instagram_positions": ["story", "reels"],
                                             "messenger_positions": ["story"]},
                      "image_label": {"name": "story"}}
        # validate_only canaries 2026-09-17 23:20 (ad set RS-BA_BROAD-W4A): with a lead-form CTA the placement-asset feed needs a link
        # (subcode 1885800) and a bare {website_url} fails "Failed to parse URL" (1611248); these three shapes validated:
        for cta in ("GET_QUOTE", "SIGN_UP"):
            cta_form = {"type": cta, "value": {"lead_gen_form_id": form_id}}
            afs = {"images": [{"hash": h45, "adlabels": [{"name": "feed"}]}, {"hash": h916, "adlabels": [{"name": "story"}]}],
                   "bodies": [{"text": ad["primary_text"]}], "titles": [{"text": ad["headline"]}], "descriptions": [{"text": ad["description"]}],
                   "call_to_action_types": [cta], "ad_formats": ["SINGLE_IMAGE"], "optimization_type": "PLACEMENT",
                   "asset_customization_rules": [feed_rule, story_rule]}
            out.append((f"afs-placement/{cta}/display_url", payload(dict(oss_base), {**afs, "link_urls": [{"website_url": LINK, "display_url": "meliabudva.com"}], "call_to_actions": [cta_form]})))
            out.append((f"afs-placement/{cta}/cta-link", payload(dict(oss_base), {**afs, "link_urls": [{"website_url": LINK}], "call_to_actions": [{"type": cta, "value": {"lead_gen_form_id": form_id, "link": LINK}}]})))
            out.append((f"afs-placement/{cta}/fbme", payload(dict(oss_base), {**afs, "link_urls": [{"website_url": "https://fb.me/"}], "call_to_actions": [cta_form]})))
        for cta in ("GET_QUOTE", "SIGN_UP"):
            ld = {"image_hash": h45, "link": LINK, "message": ad["primary_text"], "name": ad["headline"], "description": ad["description"],
                  "call_to_action": {"type": cta, "value": {"lead_gen_form_id": form_id}}}
            out.append((f"link_data-IMG45/{cta}", payload({**oss_base, "link_data": ld})))
    else:  # carousel
        cards = sorted(ad["cards"], key=lambda c: c["index"])
        for cta in ("GET_QUOTE", "SIGN_UP"):
            cta_obj = {"type": cta, "value": {"lead_gen_form_id": form_id}}
            ld = {"link": LINK, "message": ad["primary_text"], "multi_share_end_card": False, "multi_share_optimized": False,  # keep card order
                  "call_to_action": cta_obj,
                  "child_attachments": [{"image_hash": state["uploads"]["images"][Path(c["file"]).name]["hash"], "name": c["headline"], "link": LINK,
                                         "call_to_action": cta_obj} for c in cards]}
            out.append((f"carousel/{cta}", payload({**oss_base, "link_data": ld})))
    if locked:
        out = [v for v in out if v[0] == locked] + [v for v in out if v[0] != locked]
    return out


def probe_ai_creative_payload(state: dict, data: dict) -> dict:
    mode = (state["probes"].get("is_ai_generated_creative") or {}).get("decision")
    if mode == "v26-flag":
        return {**data, "is_ai_generated": "true"}
    return data


def create_creative(api: UsageApi, state: dict, ad: dict, label: str, data: dict, proven: bool = True) -> str:
    """POST /adcreatives; the first AI creative on an already-PROVEN variant doubles as the is_ai_generated probe (v26.0, field in the body)."""
    pr = state["probes"].get("is_ai_generated_creative")
    if pr is None and proven and ad.get("is_ai_generated"):
        capi = UsageApi(version=AI_PROBE_VERSION)
        pr = {"ad": ad["name"], "variant": label, "api_version": AI_PROBE_VERSION, "ts": now_utc()}
        try:
            resp = capi.call("POST", f"{api.account}/adcreatives", data={**data, "is_ai_generated": "true"})
            pr["create_accepted"] = True
            pr["creative_id"] = resp["id"]
            try:
                pr["readback_with_field"] = capi.call("GET", resp["id"], {"fields": "id,name,is_ai_generated"})
            except RuntimeError as exc:
                pr["readback_with_field"] = {"error": err_text(exc)}
            rbf = pr["readback_with_field"]
            pr["reads_back_true"] = isinstance(rbf, dict) and rbf.get("is_ai_generated") is True
            pr["decision"] = "v26-flag"
            pr["note"] = ("field accepted and reads back true" if pr["reads_back_true"] else
                          "field accepted on POST /adcreatives but NOT readable -> still sent on AI creatives; disclosure to be verified/set manually in Ads Manager")
            state["probes"]["is_ai_generated_creative"] = pr
            save_state(state)
            log(f"build: PROBE is_ai_generated on adcreative ({AI_PROBE_VERSION}): accepted, readback={json.dumps(rbf, ensure_ascii=False)[:200]}")
            return resp["id"]
        except RuntimeError as exc:
            pr["create_accepted"] = False
            pr["create_error"] = err_text(exc)
            pr["decision"] = "none"
            pr["note"] = "is_ai_generated in the creative body rejected on v26.0 -> creatives created without it; AI disclosure manually in Ads Manager"
            state["probes"]["is_ai_generated_creative"] = pr
            save_state(state)
            log(f"build: PROBE is_ai_generated on adcreative ({AI_PROBE_VERSION}): rejected: {err_text(exc)[:250]}")
    if ad.get("is_ai_generated") and (state["probes"].get("is_ai_generated_creative") or {}).get("decision") == "v26-flag":
        capi = UsageApi(version=AI_PROBE_VERSION)
        return capi.call("POST", f"{api.account}/adcreatives", data={**data, "is_ai_generated": "true"})["id"]
    return api.call("POST", f"{api.account}/adcreatives", data=data)["id"]


def validate_inline(api: UsageApi, adset_id: str, name: str, data: dict) -> None:
    """validate_only on POST /ads with the creative spec INLINE — validates creative + ad without creating anything."""
    spec = {k: (json.loads(v) if k in ("object_story_spec", "asset_feed_spec", "degrees_of_freedom_spec") else v) for k, v in data.items()}
    api.call("POST", f"{api.account}/ads", data={"name": name, "adset_id": adset_id, "status": "PAUSED", "creative": json.dumps(spec, ensure_ascii=False),
                                                 "execution_options": json.dumps(["validate_only"])})


def live_ads_of(api: UsageApi, adset_id: str) -> dict[str, dict] | None:
    try:
        rows = api.get_all(f"{adset_id}/ads", {"fields": "id,name,status,effective_status,creative{id}"})
    except RuntimeError as exc:
        log(f"build: /ads listing of {adset_id} unavailable ({err_text(exc)[:160]}) -> idempotency from state only")
        return None
    return {a["name"]: a for a in rows if a.get("effective_status") not in ("DELETED", "ARCHIVED") and a.get("status") != "DELETED"}


def phase_build(api: UsageApi, state: dict, echelon: int = 0) -> None:
    plan = load_plan()
    specs = form_specs()
    missing_forms = [k for k in specs if not state["forms"].get(k, {}).get("id")]
    assert not missing_forms, f"forms missing: {missing_forms}"
    assert all(state["adsets"].get(a["name"], {}).get("id") for a in plan["new_adsets"]), "ad sets missing — run adsets"
    dof = load_dof_spec()
    state["dof_spec_source"] = f"{DOF_DONOR_PATH.name}:dof_spec ({len(dof['creative_features_spec'])} features OPT_OUT)"
    locks: dict = state.setdefault("creative_path_locks", {})  # kind -> variant label proven on the canary
    canaries: dict = state["probes"].setdefault("ad_validate_only", {})
    done_names = {a["name"] for a in state["ads"]}
    final_skips = {s["name"] for s in state["skipped"] if s.get("final")}
    created = 0
    consecutive_errors = 0
    ads_sorted = ordered_ads(plan, echelon)
    for aspec in plan["new_adsets"]:
        adset_name = aspec["name"]
        adset_id = state["adsets"][adset_name]["id"]
        mine = [a for a in ads_sorted if a["adset_name"] == adset_name]
        if all(a["name"] in done_names or a["name"] in final_skips for a in mine):
            continue
        usage_guard(api)
        names_live = live_ads_of(api, adset_id)
        live_count = len(names_live) if names_live is not None else sum(1 for a in state["ads"] if a["adset_id"] == adset_id)
        # adopt anything already live under a planned name (created but lost before the state save)
        if names_live:
            for a in mine:
                if a["name"] in names_live and a["name"] not in done_names:
                    live = names_live[a["name"]]
                    state["ads"].append({"name": a["name"], "ad_id": live["id"], "creative_id": (live.get("creative") or {}).get("id"), "adset_name": adset_name,
                                         "adset_id": adset_id, "campaign_id": a["campaign_id"], "format": a["format"], "kind": kind_of(a["format"]),
                                         "lang": a["lang"], "target_lang": a["target_lang"], "form_key": a["form_key"], "form_id": state["forms"][a["form_key"]]["id"],
                                         "is_ai_generated": a.get("is_ai_generated"), "clone_of": a.get("clone_of"), "status": live.get("status"),
                                         "effective_status": live.get("effective_status"), "batch": BATCH, "adopted_pre_existing": True, "ts": now_utc()})
                    done_names.add(a["name"])
                    save_state(state)
                    log(f"build: {adset_name}/{a['name']}: adopted pre-existing ad {live['id']}")
        log(f"build: {adset_name} ({adset_id}): {live_count} live ads, {sum(1 for a in mine if a['name'] not in done_names and a['name'] not in final_skips)} to create")
        n_since = 0
        for a in mine:
            name = a["name"]
            if name in done_names or name in final_skips:
                continue
            if out_of_budget():
                log("build: budget exhausted — re-run to continue"); save_state(state); return
            if live_count >= ADSET_AD_CEILING:
                state["skipped"].append({"name": name, "adset_name": adset_name, "reason": f"ad set at the {ADSET_AD_CEILING}-ad ceiling", "final": False, "ts": now_utc()})
                save_state(state)
                log(f"build: {adset_name}/{name}: SKIP — ceiling {ADSET_AD_CEILING} reached ({live_count} live)")
                continue
            kind = kind_of(a["format"])
            oversize = kind == "carousel" and len(a["cards"]) > 10
            if oversize and any(s.get("reason", "").startswith("carousel >10 cards") for s in state["skipped"]):
                state["skipped"].append({"name": name, "adset_name": adset_name, "reason": f"carousel >10 cards ({len(a['cards'])}); same rejection as the first oversize carousel", "final": True, "ts": now_utc()})
                final_skips.add(name); save_state(state)
                log(f"build: {adset_name}/{name}: SKIP — {len(a['cards'])} cards, API max 10 (proven earlier)")
                continue
            if consecutive_errors >= 10:
                log("build: 10 consecutive errors — stopping the phase (re-run after inspection)"); save_state(state); return
            usage_guard(api)
            try:
                variants = creative_variants(api, state, a, dof, locks.get(kind))
            except Exception as exc:
                add_error(state, stage="build_spec", adset=adset_name, name=name, error=err_text(exc))
                log(f"build: {adset_name}/{name}: spec ERROR {err_text(exc)[:300]}")
                consecutive_errors += 1
                continue
            rejections: list[dict] = []
            proven = kind in locks
            if not proven:  # canary: validate variants INLINE (nothing created) until one passes; that one is created first
                validated = []
                for label, data in variants:
                    try:
                        validate_inline(api, adset_id, name, data)
                        validated.append((label, data))
                        log(f"build: canary {kind}: variant '{label}' validated on {name}")
                        break
                    except RuntimeError as exc:
                        rejections.append({"stage": "validate_only", "variant": label, "error": err_text(exc)})
                        log(f"build: canary {kind}: variant '{label}' rejected on validate: {err_text(exc)[:300]}")
                # after the validated one, still keep the untried remainder as real-create fallbacks
                tried = {r["variant"] for r in rejections} | {v[0] for v in validated}
                attempts = validated + [v for v in variants if v[0] not in tried]
            else:
                attempts = variants[:1]
            creative_id = ad_id = label = None
            for vlabel, vdata in attempts:
                try:
                    cid = create_creative(api, state, a, vlabel, vdata, proven=proven)
                    resp = api.call("POST", f"{api.account}/ads", data={"name": name, "adset_id": adset_id, "creative": json.dumps({"creative_id": cid}), "status": "PAUSED"})
                    creative_id, ad_id, label = cid, resp["id"], vlabel
                    break
                except Exception as exc:
                    rejections.append({"stage": "create", "variant": vlabel, "error": err_text(exc)})
                    log(f"build: {adset_name}/{name}: variant '{vlabel}' failed on create: {err_text(exc)[:300]}")
            if ad_id is None:
                if oversize:
                    state["skipped"].append({"name": name, "adset_name": adset_name, "reason": f"carousel >10 cards ({len(a['cards'])}): {rejections[-1]['error'][:220] if rejections else ''}",
                                             "variants": rejections, "final": True, "ts": now_utc()})
                    final_skips.add(name); save_state(state)
                    log(f"build: {adset_name}/{name}: SKIP — carousel >10 cards")
                    continue
                if not proven:
                    canaries[kind] = {"ad": name, "variant": None, "rejected": rejections, "ts": now_utc()}
                    state["skipped"].append({"name": name, "adset_name": adset_name, "reason": f"no {kind} variant accepted (canary)", "variants": rejections, "final": True, "ts": now_utc()})
                    final_skips.add(name); save_state(state)
                    log(f"build: {adset_name}/{name}: SKIP — no {kind} variant accepted")
                else:
                    add_error(state, stage="build", adset=adset_name, name=name, variant=attempts[0][0], error=rejections[-1]["error"] if rejections else "?")
                consecutive_errors += 1
                continue
            consecutive_errors = 0
            # the ad exists on Graph now -> record it BEFORE any further network call so a hiccup can never orphan it
            rec = {"name": name, "ad_id": ad_id, "creative_id": creative_id, "adset_name": adset_name, "adset_id": adset_id, "campaign_id": a["campaign_id"],
                   "format": a["format"], "kind": kind, "lang": a["lang"], "target_lang": a["target_lang"], "form_key": a["form_key"],
                   "form_id": state["forms"][a["form_key"]]["id"], "is_ai_generated": a.get("is_ai_generated"), "clone_of": a.get("clone_of"),
                   "creative_path": label, "cta": label.split("/")[1] if "/" in label else None, "status": "PAUSED", "effective_status": None,
                   "batch": BATCH, "echelon": echelon or (1 if a["format"] in ECHELON_FORMATS[1] else 2), "ts": now_utc()}
            if kind == "video":
                rec["video_id"] = state["uploads"]["videos"][Path(a["file"]).name]["video_id"]
                rec["thumbnail_frame_s_planned"] = a.get("thumbnail_frame_s")
            elif kind == "static":
                rec["image_hash_45"] = state["uploads"]["images"][Path(a["file"]).name]["hash"]
                rec["image_hash_916"] = state["uploads"]["images"][Path(a["placement_asset_916"]).name]["hash"]
                rec["placement_916_used"] = label.startswith("afs-placement")
            else:
                rec["cards"] = len(a["cards"])
            if not proven:
                locks[kind] = label
                canaries[kind] = {"ad": name, "variant": label, "rejected_before": rejections, "ts": now_utc()}
            state["ads"].append(rec)
            done_names.add(name)
            live_count += 1
            n_since += 1
            created += 1
            save_state(state)
            log(f"build: {adset_name}/{name}: ad {ad_id} (creative {creative_id}) PAUSED via '{label}' [{live_count}/{ADSET_AD_CEILING}]")
            try:
                if not proven:
                    chk = get_many(api, [ad_id], "status,effective_status").get(ad_id) or {}
                    rec["status"] = chk.get("status", rec["status"]); rec["effective_status"] = chk.get("effective_status")
                    save_state(state)
                    assert chk.get("status") == "PAUSED", f"ad {ad_id} status={chk.get('status')}"
                    log(f"build: creative path locked for {kind}: '{label}' (first ad {ad_id} {chk.get('status')}/{chk.get('effective_status')})")
                if n_since % 25 == 0:  # periodic batched status check (never the /ads listing edge)
                    recent = [r for r in state["ads"] if r["adset_id"] == adset_id][-25:]
                    infos = get_many(api, [r["ad_id"] for r in recent], "status,effective_status")
                    bad = [(r["name"], infos.get(r["ad_id"], {}).get("status")) for r in recent if infos.get(r["ad_id"], {}).get("status") != "PAUSED"]
                    for r in recent:
                        i = infos.get(r["ad_id"]) or {}
                        r["status"] = i.get("status", r.get("status")); r["effective_status"] = i.get("effective_status", r.get("effective_status"))
                    save_state(state)
                    log(f"build: periodic ?ids= check of last {len(recent)} ads: {'all PAUSED' if not bad else f'NOT PAUSED: {bad}'}")
                    if bad:
                        add_error(state, stage="build_status_check", adset=adset_name, error=f"ads not PAUSED: {bad}")
            except Exception as exc:
                add_error(state, stage="build_post_create", adset=adset_name, name=name, ad_id=ad_id, error=err_text(exc))
                log(f"build: {adset_name}/{name}: post-create check ERROR {err_text(exc)[:300]}")
            time.sleep(0.6)
    planned_names = {a["name"] for a in ads_sorted}
    total = sum(1 for a in state["ads"] if a["name"] in planned_names)
    skipped_here = sum(1 for n in final_skips if n in planned_names)
    log(f"build[e{echelon}]: created {created} ads this run; {total}/{len(ads_sorted)} tracked, {skipped_here} final skips, "
        f"{sum(1 for s in state['skipped'] if not s.get('final') and s['name'] in planned_names)} ceiling skips; overall {len(state['ads'])}/{len(plan['ads'])}")
    if total + skipped_here >= len(ads_sorted):
        mark_phase(state, f"build-e{echelon}" + (f"-{'+'.join(sorted(FORMAT_OVERRIDE))}" if FORMAT_OVERRIDE else ""), f"{total} ads PAUSED, {skipped_here} skipped")


# ----------------------------------------------------------------------------------------------
def phase_readback(api: UsageApi, state: dict) -> None:
    plan = load_plan()
    ads = state["ads"]
    infos = get_many(api, [a["ad_id"] for a in ads], "id,name,status,effective_status,issues_info,ad_review_feedback,creative{id},adset_id")
    dist_total: dict[str, int] = {}
    per_adset: dict[str, dict] = {}
    for rec in ads:
        info = infos.get(rec["ad_id"]) or {}
        rec["status"] = info.get("status", rec.get("status"))
        rec["effective_status"] = info.get("effective_status", rec.get("effective_status"))
        rec["issues_info"] = info.get("issues_info")
        rec["ad_review_feedback"] = info.get("ad_review_feedback")
        rec["adset_id_readback"] = info.get("adset_id")
        dist_total[rec["effective_status"]] = dist_total.get(rec["effective_status"], 0) + 1
        pa = per_adset.setdefault(rec["adset_name"], {"count": 0, "distribution": {}, "not_paused": [], "with_issues": []})
        pa["count"] += 1
        pa["distribution"][rec["effective_status"]] = pa["distribution"].get(rec["effective_status"], 0) + 1
        if rec["status"] != "PAUSED":
            pa["not_paused"].append({"name": rec["name"], "ad_id": rec["ad_id"], "status": rec["status"]})
        if rec.get("issues_info") or rec.get("ad_review_feedback"):
            pa["with_issues"].append({"name": rec["name"], "ad_id": rec["ad_id"], "issues_info": rec.get("issues_info"), "ad_review_feedback": rec.get("ad_review_feedback")})
    adset_ids = [r["id"] for r in state["adsets"].values() if r.get("id")]
    adsets_rb = get_many(api, adset_ids, "id,name,status,effective_status,daily_budget,campaign_id")
    for name, rec in state["adsets"].items():
        i = adsets_rb.get(rec.get("id")) or {}
        rec["status"] = i.get("status", rec.get("status")); rec["effective_status"] = i.get("effective_status", rec.get("effective_status")); rec["daily_budget"] = i.get("daily_budget", rec.get("daily_budget"))
    form_ids = [f["id"] for f in state["forms"].values() if f.get("id")]
    forms_rb = get_many(api, form_ids, "id,name,status,locale,leads_count")
    vids = [r["video_id"] for r in state["uploads"]["videos"].values() if r.get("video_id")]
    vid_rb = get_many(api, vids, "id,status") if vids else {}
    vdist: dict[str, int] = {}
    for v in vid_rb.values():
        s = (v.get("status") or {}).get("video_status")
        vdist[s] = vdist.get(s, 0) + 1
    state["readback"] = {"ts": now_utc(), "ads_total": len(ads), "ads_planned": len(plan["ads"]), "distribution": dist_total, "per_adset": per_adset,
                         "adsets": adsets_rb, "forms": forms_rb, "videos": vdist,
                         "skipped": state["skipped"], "errors": len(state["errors"])}
    save_state(state)
    log(f"readback: ads {len(ads)}/{len(plan['ads'])} {dist_total} | adsets {[(a.get('name'), a.get('status'), a.get('daily_budget')) for a in adsets_rb.values()]} | "
        f"forms {[(f.get('name'), f.get('status'), f.get('locale')) for f in forms_rb.values()]} | videos {vdist}")
    for name, pa in per_adset.items():
        log(f"readback: {name}: {pa['count']} ads {pa['distribution']} not_paused={len(pa['not_paused'])} issues={len(pa['with_issues'])}")
    sync_registry(state)
    mark_phase(state, "readback", "ok")


def sync_registry(state: dict) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in registry["campaigns"]}
    added_a = updated_a = 0
    plan = load_plan()
    for aspec in plan["new_adsets"]:
        entry = by_id.get(aspec["campaign_id"])
        if entry is None:
            continue
        arec = state["adsets"].get(aspec["name"]) or {}
        w4 = entry.setdefault("w4_adsets", [])
        if arec.get("id") and not any(x.get("id") == arec["id"] for x in w4):
            w4.append({"name": aspec["name"], "id": arec["id"], "slot": aspec["slot"], "daily_budget": arec.get("daily_budget"), "status": arec.get("status"),
                       "donor_adset": aspec["copy_targeting_from_adset"], "batch": BATCH})
        entry["w4_form_ids"] = {k: f["id"] for k, f in state["forms"].items() if f.get("id") and f.get("lang") == ("DE" if aspec["lang"] == "AT" else aspec["lang"])}
        for rec in [a for a in state["ads"] if a["adset_name"] == aspec["name"]]:
            existing = next((a for a in entry["ads"] if a.get("ad_id") == rec["ad_id"]), None)
            if existing:
                if existing.get("status") != rec.get("status"):
                    existing["status"] = rec.get("status"); updated_a += 1
                continue
            entry["ads"].append({"name": rec["name"], "ad_id": rec["ad_id"], "creative_id": rec["creative_id"], "type": "video" if rec["kind"] == "video" else "image",
                                 "format": rec["format"], "adset_id": rec["adset_id"], "status": rec.get("status"), "batch": BATCH})
            added_a += 1
        entry["counts"] = {"video": sum(1 for a in entry["ads"] if a.get("type") == "video"), "image": sum(1 for a in entry["ads"] if a.get("type") == "image"), "total": len(entry["ads"])}
        entry["batches"] = sorted({a.get("batch") for a in entry["ads"] if a.get("batch")})
    registry.setdefault("w4_2026_09_17", {"batch": BATCH, "ts": now_utc(), "artifact": STATE_PATH.name,
                                          "note": "wave 4 ALL creatives, 10 new PAUSED ad sets, 393 planned ads, nothing activated"})
    registry["w4_2026_09_17"].update({"ads": len(state["ads"]), "adsets": len([r for r in state["adsets"].values() if r.get("id")]),
                                      "forms": {k: f["id"] for k, f in state["forms"].items() if f.get("id")}, "updated": now_utc()})
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state["registry_appended"] = True
    save_state(state)
    log(f"registry: +{added_a} ads, {updated_a} status updates in {REGISTRY_PATH.name} (batch {BATCH})")


# ----------------------------------------------------------------------------------------------
def phase_status(state: dict) -> None:
    plan = load_plan()
    print(f"batch {state['batch']} | forms {sum(1 for f in state['forms'].values() if f.get('id'))}/10 | adsets {sum(1 for a in state['adsets'].values() if a.get('id'))}/10 | "
          f"videos {sum(1 for v in state['uploads']['videos'].values() if v.get('status') == 'ready')} ready / {len(state['uploads']['videos'])} | images {len(state['uploads']['images'])} | "
          f"ads {len(state['ads'])}/{len(plan['ads'])} | skipped {len(state['skipped'])} | errors {len(state['errors'])}")
    for k, f in state["forms"].items():
        print(f"  form {k:18} {f.get('id')} {f.get('name')} locale={(f.get('readback') or {}).get('locale')} ok={f.get('readback_ok')}")
    for a in plan["new_adsets"]:
        r = state["adsets"].get(a["name"], {})
        mine = [x for x in state["ads"] if x["adset_name"] == a["name"]]
        print(f"  adset {a['name']:28} {r.get('id')} {r.get('status')} budget {r.get('daily_budget')} | ads {len(mine)}/{a['ads']} | "
              f"{ {k: sum(1 for x in mine if x['kind'] == k) for k in ('video', 'static', 'carousel')} }")
    print("probes:", json.dumps({k: (v.get('decision') or v.get('variant')) for k, v in state["probes"].items() if isinstance(v, dict)}, ensure_ascii=False))
    print("locks:", state.get("creative_path_locks"))
    for s in state["skipped"]:
        print("SKIPPED:", s["name"], "-", s["reason"][:160])
    for e in state["errors"][-20:]:
        print("ERROR:", json.dumps(e, ensure_ascii=False)[:300])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["probe", "forms", "adsets", "media", "build", "readback", "status"])
    ap.add_argument("--budget-sec", type=int, default=0, help="0 = unlimited")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--echelon", type=int, default=0, choices=[0, 1, 2], help="1 = VID916+IMG45+CAR45, 2 = VID45, 0 = all")
    ap.add_argument("--formats", default="", help="comma-separated subset of VID916,IMG45,CAR45,VID45 (overrides --echelon)")
    args = ap.parse_args()
    if args.budget_sec:
        DEADLINE[0] = time.time() + args.budget_sec
    if args.formats:
        FORMAT_OVERRIDE.update(f.strip() for f in args.formats.split(",") if f.strip())
        assert FORMAT_OVERRIDE <= set(FORMAT_ORDER), f"unknown formats {FORMAT_OVERRIDE - set(FORMAT_ORDER)}"
    state = load_state()
    if args.phase == "status":
        phase_status(state); return
    api = UsageApi()
    assert api.account == EXPECTED_ACCOUNT, f"account mismatch: {api.account}"
    assert api.page_id == EXPECTED_PAGE, f"page mismatch: {api.page_id}"
    log(f"phase '{args.phase}' (echelon {args.echelon or 'all'}) start: token {mask(api.token)}, api {api.version} (AI probes on {AI_PROBE_VERSION}), account {api.account}, "
        f"budget {'unlimited' if not args.budget_sec else args.budget_sec}")
    save_state(state)
    {
        "probe": lambda: phase_probe(api, state),
        "forms": lambda: phase_forms(api, state),
        "adsets": lambda: phase_adsets(api, state),
        "media": lambda: phase_media(api, state, args.workers, args.echelon),
        "build": lambda: phase_build(api, state, args.echelon),
        "readback": lambda: phase_readback(api, state),
    }[args.phase]()
    save_state(state)
    log(f"phase '{args.phase}' finished; state at {STATE_PATH.name}")


if __name__ == "__main__":
    main()
