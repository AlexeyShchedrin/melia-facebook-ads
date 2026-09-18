"""Wave-4 video transcode (coordinator 2026-09-17 22:40): shrink VID916/VID45 masters before upload to save API time quota.

Output: <scratchpad>/w4_transcode/<same basename>; manifest.json next to it (rewritten after every file).
ffmpeg: -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -r <source fps> -c:a aac -b:a 128k -movflags +faststart (resolution unchanged).
Accept the transcode only if: size <= 70% of the source AND |duration delta| <= 0.15 s AND audio present iff the source had audio.
Sources in OneDrive are never touched. Order: VID916 (echelon 1) first, then VID45. 2 parallel ffmpeg processes.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFBIN = Path(r"C:\Users\avshc\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin")
FFMPEG, FFPROBE = FFBIN / "ffmpeg.exe", FFBIN / "ffprobe.exe"
OUT_DIR = Path(r"C:\Users\avshc\AppData\Local\Temp\claude\C--Users-avshc-kvadra-workspace\bdf8818a-afa8-4cd8-aaf1-b640dab8f00c\scratchpad\w4_transcode")
MANIFEST = OUT_DIR / "manifest.json"
PLAN = Path(__file__).resolve().parent / "w4_wave_all_now.json"
LOG = Path(__file__).resolve().parent / "w4_transcode.log"
WORKERS = 2
_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _lock:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def probe(path: Path) -> dict:
    r = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration,size", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr[-300:]}")
    j = json.loads(r.stdout)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {"duration": float(j["format"]["duration"]), "size": int(j["format"]["size"]), "width": v.get("width"), "height": v.get("height"),
            "fps": v.get("r_frame_rate") or v.get("avg_frame_rate"), "vcodec": v.get("codec_name"), "audio": a is not None, "acodec": (a or {}).get("codec_name")}


def load_manifest() -> dict:
    if MANIFEST.exists():
        for _ in range(20):
            try:
                return json.loads(MANIFEST.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                time.sleep(0.2)
    return {}


def save_manifest(m: dict) -> None:
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    for _ in range(40):
        try:
            tmp.replace(MANIFEST)
            return
        except PermissionError:
            time.sleep(0.2)
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")


def ordered_videos() -> list[Path]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    rank = {a["name"]: i for i, a in enumerate(plan["new_adsets"])}
    order = {"VID916": 0, "VID45": 1}
    seen: dict[str, Path] = {}
    for a in sorted([x for x in plan["ads"] if x["format"] in order], key=lambda x: (order[x["format"]], rank[x["adset_name"]])):
        p = Path(a["file"])
        seen.setdefault(p.name, p)
    return list(seen.values())


def transcode_one(src: Path, manifest: dict) -> None:
    dst = OUT_DIR / src.name
    rec: dict = {"src": str(src), "dst": str(dst), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        sp = probe(src)
        rec.update({"src_size": sp["size"], "src_duration": sp["duration"], "src_audio": sp["audio"], "fps": sp["fps"], "resolution": f"{sp['width']}x{sp['height']}"})
        cmd = [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-r", str(sp["fps"])]
        if sp["audio"]:
            cmd += ["-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart", str(dst)]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        rec["encode_sec"] = round(time.time() - t0, 1)
        if r.returncode != 0 or not dst.exists():
            raise RuntimeError(f"ffmpeg rc={r.returncode}: {r.stderr[-300:]}")
        dp = probe(dst)
        rec.update({"dst_size": dp["size"], "dst_duration": dp["duration"], "dst_audio": dp["audio"], "dst_resolution": f"{dp['width']}x{dp['height']}"})
        ratio = dp["size"] / max(1, sp["size"])
        rec["ratio"] = round(ratio, 3)
        checks = {"size_le_70pct": ratio <= 0.70, "duration_within_0.15s": abs(dp["duration"] - sp["duration"]) <= 0.15,
                  "audio_preserved": dp["audio"] == sp["audio"], "resolution_same": (dp["width"], dp["height"]) == (sp["width"], sp["height"])}
        rec["checks"] = checks
        rec["ok"] = all(checks.values())
        rec["use"] = "transcoded" if rec["ok"] else "original"
        log(f"{src.name}: {sp['size'] / 1048576:.1f} -> {dp['size'] / 1048576:.1f} MB ({ratio:.0%}), dur {sp['duration']:.2f}->{dp['duration']:.2f}, "
            f"audio {sp['audio']}->{dp['audio']}, {rec['encode_sec']}s -> {rec['use']}" + ("" if rec["ok"] else f" {checks}"))
    except Exception as exc:
        rec["ok"] = False
        rec["use"] = "original"
        rec["error"] = str(exc)[:400]
        log(f"{src.name}: FAILED {str(exc)[:300]} -> original")
    with _lock:
        manifest[src.name] = rec
        save_manifest(manifest)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    videos = ordered_videos()
    todo = [p for p in videos if manifest.get(p.name, {}).get("use") is None]
    log(f"transcode: {len(videos)} videos, {len(videos) - len(todo)} done, {len(todo)} to do with {WORKERS} ffmpeg processes -> {OUT_DIR}")
    queue = list(todo)

    def worker() -> None:
        while True:
            with _lock:
                if not queue:
                    return
                p = queue.pop(0)
            transcode_one(p, manifest)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ok = sum(1 for r in manifest.values() if r.get("ok"))
    src_mb = sum(r.get("src_size", 0) for r in manifest.values() if r.get("ok")) / 1048576
    dst_mb = sum(r.get("dst_size", 0) for r in manifest.values() if r.get("ok")) / 1048576
    log(f"transcode: done — {ok}/{len(manifest)} accepted; accepted set {src_mb:.0f} -> {dst_mb:.0f} MB; {sum(1 for r in manifest.values() if not r.get('ok'))} fall back to originals")


if __name__ == "__main__":
    main()
