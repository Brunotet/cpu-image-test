import glob, json, os, subprocess, traceback

IDS = "__IDS__".split(",")
OUT = "/kaggle/working/out"
os.makedirs(OUT, exist_ok=True)
os.makedirs("/kaggle/working/dl", exist_ok=True)

def sh(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

rc, o = sh("pip install -q -U yt-dlp faster-whisper")
open(OUT + "/pip.txt", "w").write(o[-1500:])
rc, o = sh("which ffmpeg || (apt-get update -qq && apt-get install -y -qq ffmpeg)")
from faster_whisper import WhisperModel
model = WhisperModel("medium", device="cpu", compute_type="int8")
log = []
for vid in IDS:
    rec = {"id": vid}
    errs = []
    for client in ["", "android_vr", "tv", "mweb", "web_embedded", "ios", "web_safari"]:
        ea = (" --extractor-args youtube:player_client=" + client) if client else ""
        rc, o = sh("yt-dlp --no-playlist -f bestaudio/best -x --audio-format mp3 -o '/kaggle/working/dl/%(id)s.%(ext)s'" + ea + " https://www.youtube.com/shorts/" + vid)
        errs.append("%s rc=%s %s" % (client or "default", rc, o[-160:].replace(chr(10), " ")))
        if glob.glob("/kaggle/working/dl/" + vid + ".*"):
            break
    rec["tries"] = " || ".join(errs)[-1600:]
    files = glob.glob("/kaggle/working/dl/" + vid + ".*")
    if files:
        try:
            segs, info = model.transcribe(files[0], beam_size=5, language="en")
            lines = ["[%d:%02d] %s" % (int(s.start) // 60, int(s.start) % 60, s.text.strip()) for s in segs]
            open(OUT + "/" + vid + ".txt", "w").write(chr(10).join(lines))
            rec.update({"source": "whisper medium on the real audio", "words": sum(len(l.split()) for l in lines), "audio_seconds": round(info.duration, 1)})
        except Exception:
            rec["error"] = traceback.format_exc()[-400:]
    else:
        rec["source"] = "download failed"
    log.append(rec)
    json.dump(log, open(OUT + "/log.json", "w"), indent=1)
print(json.dumps(log, indent=1))
