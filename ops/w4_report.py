"""Offline report for the wave-4 rollout: reads ops/w4_rollout_2026-09-17.json + ops/w4_wave_all_now.json, prints the tables."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPS = Path(__file__).resolve().parent
import time


def _load(path: Path) -> dict:
    for _ in range(40):  # the rollout process replaces the file atomically; Windows briefly locks it
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.25)
    return json.loads(path.read_text(encoding="utf-8"))


state = _load(OPS / "w4_rollout_2026-09-17.json")
plan = json.loads((OPS / "w4_wave_all_now.json").read_text(encoding="utf-8"))

ECHELON_FORMATS = {1: {"VID916", "IMG45", "CAR45"}, 2: {"VID45"}}
echelon = int(sys.argv[sys.argv.index("--echelon") + 1]) if "--echelon" in sys.argv else 0
fmts = ECHELON_FORMATS.get(echelon)
plan_ads = [a for a in plan["ads"] if not fmts or a["format"] in fmts]
planned_per_adset = Counter(a["adset_name"] for a in plan_ads)
ads = [a for a in state["ads"] if not fmts or a["format"] in fmts]
print(f"# wave-4 rollout report — echelon {echelon or 'all'} — artifact updated {state.get('updated_utc')}")
by_adset = {a["name"]: a for a in plan["new_adsets"]}
errs_by_adset = Counter(e.get("adset") for e in state["errors"] if e.get("stage", "").startswith("build"))
plan_names = {a["name"] for a in plan_ads}
skips_by_adset = Counter(s.get("adset_name") for s in state["skipped"] if s["name"] in plan_names)

print("== 1. Ad sets (all PAUSED, nothing activated)")
print(f"{'adset':28} {'adset_id':20} {'budget/day':>10} {'status':>8} {'planned':>7} {'created':>7} {'PAUSED':>6} {'skipped':>7} {'errors':>6}  kinds")
tot_planned = tot_created = 0
for spec in plan["new_adsets"]:
    rec = state["adsets"].get(spec["name"], {})
    mine = [a for a in ads if a["adset_name"] == spec["name"]]
    paused = sum(1 for a in mine if a.get("status") == "PAUSED")
    kinds = Counter(a["format"] for a in mine)
    planned = planned_per_adset.get(spec["name"], 0)
    tot_planned += planned; tot_created += len(mine)
    print(f"{spec['name']:28} {rec.get('id', '-'):20} {('€' + str(int(rec.get('daily_budget') or 0) // 100)):>10} {str(rec.get('status')):>8} {planned:>7} {len(mine):>7} {paused:>6} "
          f"{skips_by_adset.get(spec['name'], 0):>7} {errs_by_adset.get(spec['name'], 0):>6}  {dict(kinds)}")
print(f"{'TOTAL':28} {'':20} {'':>10} {'':>8} {tot_planned:>7} {tot_created:>7} {sum(1 for a in ads if a.get('status') == 'PAUSED'):>6} {len(state['skipped']):>7} {sum(errs_by_adset.values()):>6}")
rb = state.get("readback", {})
if rb:
    print(f"readback {rb.get('ts')}: effective_status distribution {rb.get('distribution')} | adsets {[(a.get('name'), a.get('status'), a.get('daily_budget')) for a in rb.get('adsets', {}).values()]}")
    for n, pa in rb.get("per_adset", {}).items():
        if pa.get("not_paused") or pa.get("with_issues"):
            print(f"   {n}: not_paused={pa['not_paused']} with_issues={[(x['name'], x.get('issues_info')) for x in pa['with_issues']]}")

print("\n== 2. Forms (form_key -> form_id, locale, headline)")
for k, f in state["forms"].items():
    r = f.get("readback", {})
    ext = f.get("readback_ext", {})
    print(f"{k:18} {f.get('id'):18} {r.get('locale'):6} {r.get('status'):7} {f.get('name'):32} custom={[q['key'] for q in r.get('questions', []) if q.get('type') == 'CUSTOM']} "
          f"headline={ext.get('question_page_custom_headline')!r}")

print("\n== 3. Probes")
for k in ("is_ai_generated_video", "is_ai_generated_image", "is_ai_generated_creative"):
    p = state["probes"].get(k) or {}
    print(f"{k:26} accepted={p.get('upload_accepted', p.get('create_accepted'))} reads_back_true={p.get('reads_back_true')} decision={p.get('decision')} "
          f"readback={json.dumps(p.get('readback_with_field'), ensure_ascii=False)[:160]} err={(p.get('upload_error') or p.get('create_error') or '')[:160]}")
print("form validate_only:", json.dumps(state["probes"].get("form_validate_only"), ensure_ascii=False)[:200])
print("adset validate_only:", json.dumps(state["probes"].get("adset_validate_only"), ensure_ascii=False)[:200])
print("ad canaries:", json.dumps({k: {"ad": v.get("ad"), "variant": v.get("variant"), "rejected": [(r.get("variant"), (r.get("error") or "")[:140]) for r in (v.get("rejected_before") or v.get("rejected") or [])]}
                                  for k, v in (state["probes"].get("ad_validate_only") or {}).items()}, ensure_ascii=False, indent=1))
print("creative path locks:", state.get("creative_path_locks"))
print("paths used:", dict(Counter(a.get("creative_path") for a in ads)))
print("CTA used:", dict(Counter(a.get("cta") for a in ads)))
print("AI flag: videos flag_sent", dict(Counter((v.get('is_ai_generated'), v.get('ai_flag_sent')) for v in state['uploads']['videos'].values())),
      "| images flag_sent", dict(Counter((v.get('is_ai_generated'), v.get('ai_flag_sent')) for v in state['uploads']['images'].values())))

print("\n== 4. Not created / errors")
for s in state["skipped"]:
    if s["name"] in plan_names:
        print(f"SKIP  {s['name']:60} {s.get('adset_name'):26} {s['reason'][:200]}")
for e in state["errors"]:
    print(f"ERROR {e.get('stage'):18} {str(e.get('name') or e.get('file') or e.get('form') or e.get('adset') or ''):60} {str(e.get('error'))[:220]}")

print("\n== 5. Media")
v = state["uploads"]["videos"]; i = state["uploads"]["images"]
print(f"videos: {len(v)} uploaded, {sum(1 for x in v.values() if x.get('status') == 'ready')} ready, {sum(1 for x in v.values() if x.get('status') == 'error')} error | images: {len(i)}")
secs = [x.get("upload_sec") for x in v.values() if x.get("upload_sec")]
mb = [x.get("size_mb") for x in v.values() if x.get("upload_sec")]
if secs:
    print(f"upload: {sum(mb):.0f} MB in {sum(secs)} worker-seconds -> {sum(mb) / max(1, sum(secs)):.2f} MB/s per worker")
print("phase log:", [(p["phase"], p["ts"]) for p in state["phase_log"]])
