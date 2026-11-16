import os, json, subprocess, glob, traceback, urllib.request, urllib.error
ids = [i.strip() for i in os.environ["IDS"].split(",") if i.strip()]
os.makedirs("ytout", exist_ok=True)
os.makedirs("yt_dl", exist_ok=True)
key = os.environ.get("YT_API_KEY", "")
meta = {}
try:
    url = "https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id=" + ",".join(ids) + "&key=" + key
    data = json.load(urllib.request.urlopen(url, timeout=30))
    for it in data.get("items", []):
        st = it.get("statistics", {})
        meta[it["id"]] = {"title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"], "published": it["snippet"]["publishedAt"], "views": st.get("viewCount"), "likes": st.get("likeCount"), "comments": st.get("commentCount"), "duration": it["contentDetails"]["duration"], "description": it["snippet"].get("description", "")[:500]}
    meta["_status"] = "ok, %d of %d videos found" % (len(data.get("items", [])), len(ids))
except urllib.error.HTTPError as e:
    meta["_status"] = "http %s: %s" % (e.code, e.read().decode()[:300])
except Exception as e:
    meta["_status"] = "error: " + str(e)[:300]
json.dump(meta, open("ytout/meta.json", "w"), indent=1)
from faster_whisper import WhisperModel
model = WhisperModel(os.environ.get("MODEL", "medium"), device="cpu", compute_type="int8")
log = []
cookies = ["--cookies", "cookies.txt"] if os.path.exists("cookies.txt") else []
for vid in ids:
    rec = {"id": vid}
    try:
        cmd = ["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "-o", "yt_dl/%(id)s.%(ext)s"] + cookies + ["https://www.youtube.com/shorts/" + vid]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        rec["yt_dlp_rc"] = r.returncode
        rec["yt_dlp_err"] = (r.stderr or "")[-500:]
        files = glob.glob("yt_dl/" + vid + ".*")
        if files:
            segs, info = model.transcribe(files[0], beam_size=5)
            lines = ["[%d:%02d] %s" % (int(s.start) // 60, int(s.start) % 60, s.text.strip()) for s in segs]
            open("ytout/%s.txt" % vid, "w").write(chr(10).join(lines))
            rec.update({"source": "whisper audio", "language": info.language, "audio_seconds": round(info.duration, 1), "words": sum(len(l.split()) for l in lines)})
        else:
            rec["source"] = "audio download failed"
    except Exception:
        rec["error"] = traceback.format_exc()[-600:]
    if rec.get("source") != "whisper audio":
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            try:
                parts = YouTubeTranscriptApi().fetch(vid)
                texts = [(p.start, p.text) for p in parts]
            except Exception:
                parts = YouTubeTranscriptApi.get_transcript(vid)
                texts = [(p["start"], p["text"]) for p in parts]
            lines = ["[%d:%02d] %s" % (int(t) // 60, int(t) % 60, x) for t, x in texts]
            open("ytout/%s.txt" % vid, "w").write(chr(10).join(lines))
            rec["source"] = "captions fallback (not whisper)"
            rec["words"] = sum(len(l.split()) for l in lines)
        except Exception as e:
            rec["fallback_error"] = str(e)[:300]
    log.append(rec)
json.dump(log, open("ytout/log.json", "w"), indent=1)
print(json.dumps(log, indent=1))
