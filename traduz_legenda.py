#!/usr/bin/env python3
"""traduz-legenda: translate the English subtitle embedded in a video into Brazilian Portuguese (or another language) with an
LLM, and save it next to the video as `<video>.pt-BR.srt`. Made for anime that comes out with English subtitles only.

  traduz_legenda.py VIDEO [VIDEO ...] [--lang pt-BR] [--track N] [--out DIR] [--dry-run]
  traduz_legenda.py --sonarr http://localhost:8989 [--days 1] [--max 6]   # anime in Sonarr without a Portuguese subtitle

Environment: LLM_API_KEY (required), LLM_BASE_URL (default https://api.deepseek.com), LLM_MODEL (default deepseek-flash),
LLM_PRICE_IN / LLM_PRICE_OUT (USD per million tokens, for the cost report), MAX_USD (stop when a run passes it, default 1.0),
SONARR_API_KEY (for --sonarr), JELLYFIN_URL + JELLYFIN_API_KEY (optional: tell Jellyfin the new file exists).
Needs ffmpeg/ffprobe. Standard library only. On our server an episode costs about US$ 0.002-0.006 with DeepSeek.
License: MIT. https://github.com/CaioGuerras/traduz-legenda"""
import argparse, datetime as dt, json, os, re, subprocess, sys, tempfile, time, urllib.request

BATCH = 60
LANGS = {"pt-BR": "Brazilian Portuguese", "pt": "European Portuguese", "es": "Spanish", "fr": "French", "it": "Italian", "de": "German"}
PROMPT = ("You translate anime subtitles from English into natural, colloquial {lang}, like a professional subtitle. Keep names and "
          "Japanese honorifics (-san, -kun, -chan, senpai). Input lines look like 'N|text'. Output EXACTLY the same lines "
          "'N|translation', same count and order, no comments. '\\N' marks a line break: keep it.")
BASE = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "deepseek-flash")
PRICE_IN, PRICE_OUT = float(os.environ.get("LLM_PRICE_IN", "0.3")), float(os.environ.get("LLM_PRICE_OUT", "1.2"))
MAX_USD = float(os.environ.get("MAX_USD", "1.0"))
spent = 0.0


def pick_track(video):
    """English DIALOGUE track: text codec, not forced, not 'signs/songs'; prefers non-SDH. Reads only the header."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                        "stream=index,codec_name:stream_tags=language,title:stream_disposition=forced,hearing_impaired",
                        "-of", "json", video], capture_output=True, text=True, timeout=300)
    cands = []
    for st in json.loads(r.stdout or "{}").get("streams", []):
        tags, disp, title = st.get("tags", {}), st.get("disposition", {}), (st.get("tags", {}).get("title") or "").lower()
        if (tags.get("language") or "").lower() not in ("eng", "en"):
            continue
        if st.get("codec_name") not in ("ass", "ssa", "subrip", "mov_text", "webvtt", "text"):
            continue
        if disp.get("forced") or any(k in title for k in ("sign", "song", "forced", "lyrics")):
            continue
        cands.append((bool(disp.get("hearing_impaired")) or "sdh" in title, st["index"]))
    return str(sorted(cands)[0][1]) if cands else None


def read_srt(path):
    out = []
    for block in re.split(r"\n\s*\n", open(path, encoding="utf-8", errors="replace").read().strip()):
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            out.append([lines[1], "\\N".join(lines[2:])])
    return out


def clean(t):
    return re.sub(r"<[^>]+>|\{\\[^}]*\}", "", t).strip()


def chat(system, user):
    body = {"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": 8000, "temperature": 0.3}
    if "deepseek" in BASE:
        body["thinking"] = {"type": "disabled"}  # DeepSeek: no reasoning tokens for a plain translation (cheaper, faster)
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def translate_batch(lang, lines):
    global spent
    text = "\n".join(f"{i}|{t}" for i, t in lines)
    for attempt in range(3):
        if spent > MAX_USD:
            raise SystemExit(f"cost cap reached (MAX_USD={MAX_USD}); stopping")
        try:
            res = chat(PROMPT.format(lang=LANGS.get(lang, lang)), text)
        except Exception as e:
            print(f"  API error ({str(e)[:80]}), retrying", flush=True)
            time.sleep(10 * (attempt + 1))
            continue
        u = res.get("usage", {})
        spent += (u.get("prompt_tokens", 0) * PRICE_IN + u.get("completion_tokens", 0) * PRICE_OUT) / 1e6
        got = {}
        for line in res["choices"][0]["message"]["content"].splitlines():
            m = re.match(r"\s*(\d+)\|(.*)$", line)
            if m:
                got[int(m.group(1))] = m.group(2).strip()
        if all(i in got for i, _ in lines):
            return got
    raise RuntimeError("incomplete translation after 3 attempts")


def notify_jellyfin(path):
    url, key = os.environ.get("JELLYFIN_URL"), os.environ.get("JELLYFIN_API_KEY")
    if not (url and key):
        return
    body = json.dumps({"Updates": [{"Path": path, "UpdateType": "Created"}]}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/Library/Media/Updated", data=body, method="POST",
                                 headers={"X-Emby-Token": key, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print(f"  (Jellyfin notify failed: {str(e)[:80]})")


def translate_video(video, lang, track=None, out_dir=None, dry=False):
    base = os.path.splitext(os.path.join(out_dir, os.path.basename(video)) if out_dir else video)[0]
    target = f"{base}.{lang}.srt"
    if os.path.exists(target):
        print(f"already there: {os.path.basename(target)}")
        return False
    track = track or pick_track(video)
    if track is None:
        print(f"{os.path.basename(video)[:70]}: no English text subtitle; skipped")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        en = os.path.join(tmp, "en.srt")
        t0 = time.time()
        subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-i", video, "-map", f"0:{track}", "-c:s", "srt", en],
                       check=True, timeout=3600)
        lines = read_srt(en)
        print(f"{os.path.basename(video)[:70]}: {len(lines)} lines (track {track}), extracted in {time.time() - t0:.0f}s", flush=True)
        if dry:
            return False
        before, done = spent, {}
        texts = [(i, clean(t)) for i, (_, t) in enumerate(lines)]
        for k in range(0, len(texts), BATCH):
            batch = [(i, t) for i, t in texts[k:k + BATCH] if t]
            if batch:
                done.update(translate_batch(lang, batch))
        with open(target + ".tmp", "w", encoding="utf-8") as f:
            for n, (stamp, txt) in enumerate(lines):
                f.write(f"{n + 1}\n{stamp}\n{done.get(n, clean(txt)).replace(chr(92) + 'N', chr(10))}\n\n")
        os.replace(target + ".tmp", target)
        notify_jellyfin(target)
        print(f"  -> {os.path.basename(target)} (US$ {spent - before:.4f})", flush=True)
        return True


def sonarr_candidates(url, days, lang):
    def get(path):
        req = urllib.request.Request(url.rstrip("/") + "/api/v3/" + path, headers={"X-Api-Key": os.environ["SONARR_API_KEY"]})
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    code = {"pt-BR": "por", "pt": "por", "es": "spa", "fr": "fre", "it": "ita", "de": "ger"}.get(lang, lang)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days) if days else None
    queued = {q.get("episodeId") for q in get("queue?pageSize=1000")["records"]}
    for s in get("series"):
        if s["seriesType"] != "anime":
            continue
        eps = {e["episodeFileId"]: e["id"] for e in get(f"episode?seriesId={s['id']}") if e.get("episodeFileId")}
        for f in get(f"episodefile?seriesId={s['id']}"):
            mi = f.get("mediaInfo") or {}
            audio, subs = (mi.get("audioLanguages") or "").lower(), (mi.get("subtitles") or "").lower()
            if not mi or code in audio or code in subs or "eng" not in subs or eps.get(f["id"]) in queued:
                continue
            if since and dt.datetime.fromisoformat(f["dateAdded"].replace("Z", "+00:00")) < since:
                continue
            base = os.path.splitext(f["path"])[0]
            if any(os.path.exists(f"{base}{suf}") for suf in (f".{lang}.srt", f".{code}.srt", f".{lang}.ass")):
                continue
            yield f["path"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--lang", default="pt-BR")
    ap.add_argument("--track")
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sonarr")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--max", type=int, default=6)
    a = ap.parse_args()
    if "LLM_API_KEY" not in os.environ and not a.dry_run:
        sys.exit("set LLM_API_KEY")
    videos = list(a.videos) or (list(sonarr_candidates(a.sonarr, a.days, a.lang))[:a.max] if a.sonarr else [])
    if not videos:
        sys.exit(__doc__ if not a.sonarr else 0)
    n = sum(translate_video(v, a.lang, a.track, a.out, a.dry_run) for v in videos)
    print(f"{n} translated, US$ {spent:.4f}")


if __name__ == "__main__":
    main()
