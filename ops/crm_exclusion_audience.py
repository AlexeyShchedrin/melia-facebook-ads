"""CRM contacts -> Meta Custom Audience (hashed on the CRM box) -> exclusion on the WAVE-4 ad sets.

Runs ON the CRM box (root@crm.kvadra.me) with /opt/facebook-ads/.venv/bin/python:
  python crm_exclusion_audience.py build   # export leads (project 1) -> SHA256 -> create/refresh audience -> upload
  python crm_exclusion_audience.py exclude <adset_id> [...]   # add the audience to excluded_custom_audiences
  python crm_exclusion_audience.py status  # audience id / approximate size / adsets' exclusions

PII never leaves the box: only SHA256 hashes go to Meta (schema EMAIL+PHONE, Meta normalization rules).
Never prints tokens. Idempotent by audience name. Weekly refresh = `build` again (usersreplace session).
"""
import csv, hashlib, io, json, os, re, subprocess, sys, time, urllib.parse, urllib.request

AUD_NAME = "MB_CRM_ALL_CONTACTS_EXCL"
ACT = "act_776404808314031"
ENV = {}
for line in open("/opt/facebook-ads/.env", encoding="utf-8"):
    m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
    if m: ENV[m.group(1)] = m.group(2).strip().strip('"').strip("'")
TOK = ENV["META_SYSTEM_USER_TOKEN"]
G = "https://graph.facebook.com/v25.0"
W4_ADSETS = ["120252278948590233", "120252278949120233", "120252278949750233", "120252278950310233", "120252278950760233",
             "120252278951570233", "120252278952000233", "120252278952520233", "120252278952800233", "120252278953110233"]

def graph(method, path, params=None, data=None):
    params = dict(params or {}); params["access_token"] = TOK
    url = f"{G}/{path}?{urllib.parse.urlencode(params)}"
    body = urllib.parse.urlencode(data).encode() if data else None
    for attempt in range(5):
        req = urllib.request.Request(url, data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            j = json.loads(e.read().decode() or "{}"); err = j.get("error", {})
            if err.get("code") in (17, 613, 80004, 4, 2):
                time.sleep(60 * (attempt + 1)); continue
            return j
    return {"error": {"message": "retries exhausted"}}

def sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

def export_contacts():
    sql = ("COPY (SELECT coalesce(regexp_replace(phone, '\\D', '', 'g'), '') AS phone, coalesce(lower(trim(email)), '') AS email "
           "FROM leads WHERE project_id=1 AND (phone IS NOT NULL OR email IS NOT NULL)) TO STDOUT WITH CSV")
    out = subprocess.run(["docker", "compose", "-f", "/opt/melia-crm/docker-compose.yml", "exec", "-T", "postgres",
                          "psql", "-U", "melia", "-d", "melia", "-c", sql], capture_output=True, text=True, check=True).stdout
    rows = []; seen = set()
    for phone, email in csv.reader(io.StringIO(out)):
        phone = phone.lstrip("0")
        if len(phone) < 8: phone = ""
        if "@" not in email: email = ""
        if not phone and not email: continue
        key = (phone, email)
        if key in seen: continue
        seen.add(key); rows.append([sha(email) if email else "", sha(phone) if phone else ""])
    return rows

def find_audience():
    r = graph("GET", f"{ACT}/customaudiences", {"fields": "id,name,approximate_count_lower_bound,approximate_count_upper_bound,subtype", "limit": 200})
    for a in r.get("data", []):
        if a.get("name") == AUD_NAME: return a
    return None

def build():
    rows = export_contacts()
    print(f"contacts exported+hashed: {len(rows)}")
    aud = find_audience()
    if not aud:
        r = graph("POST", f"{ACT}/customaudiences", data={"name": AUD_NAME, "subtype": "CUSTOM", "customer_file_source": "USER_PROVIDED_ONLY",
                                                          "description": "All Melia CRM contacts (project 1) — exclusion for prospecting ad sets; refreshed weekly"})
        if "error" in r: print("CREATE ERROR:", json.dumps(r["error"], ensure_ascii=False)); return None
        aud = {"id": r["id"], "name": AUD_NAME}; print("audience created:", aud["id"])
    else:
        print("audience exists:", aud["id"])
    aid = aud["id"]
    # replace semantics (session) so weekly refresh removes nobody by accident but reflects the full list
    session_id = int(time.time()) % 2_000_000_000
    batches = [rows[i:i + 5000] for i in range(0, len(rows), 5000)]
    for i, b in enumerate(batches):
        payload = {"schema": ["EMAIL", "PHONE"], "data": b}
        session = {"session_id": session_id, "batch_seq": i + 1, "last_batch_flag": i == len(batches) - 1, "estimated_num_total": len(rows)}
        r = graph("POST", f"{aid}/usersreplace", data={"payload": json.dumps(payload), "session": json.dumps(session)})
        if "error" in r:
            print(f"batch {i+1} ERROR:", json.dumps(r["error"], ensure_ascii=False)); return aid
        print(f"batch {i+1}/{len(batches)}: received {r.get('num_received')} invalid {r.get('num_invalid_entries')}")
    return aid

def exclude(adsets):
    aud = find_audience()
    if not aud: print("no audience"); return
    for asid in adsets:
        cur = graph("GET", asid, {"fields": "name,targeting"})
        if "error" in cur: print(asid, "READ ERROR", cur["error"].get("message")); continue
        t = cur["targeting"]; ex = t.get("excluded_custom_audiences", [])
        if any(x.get("id") == aud["id"] for x in ex): print(f"{cur['name']}: already excluded"); continue
        t["excluded_custom_audiences"] = ex + [{"id": aud["id"]}]
        r = graph("POST", asid, data={"targeting": json.dumps(t)})
        rb = graph("GET", asid, {"fields": "targeting{excluded_custom_audiences}"})
        got = [x.get("id") for x in rb.get("targeting", {}).get("excluded_custom_audiences", [])]
        print(f"{cur['name']}: {r.get('success', r.get('error',{}).get('message','')[:80])} -> excluded {got}")
        time.sleep(3)

def status():
    aud = find_audience(); print("audience:", json.dumps(aud, ensure_ascii=False))
    for asid in W4_ADSETS:
        rb = graph("GET", asid, {"fields": "name,targeting{excluded_custom_audiences}"})
        print(rb.get("name"), [x.get("name") or x.get("id") for x in rb.get("targeting", {}).get("excluded_custom_audiences", [])])

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build": build()
    elif cmd == "exclude": exclude(sys.argv[2:] or W4_ADSETS)
    else: status()
