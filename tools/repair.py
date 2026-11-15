import re, subprocess, sys, os, traceback, shutil
f = sys.argv[1]
out_dir = os.path.dirname(os.path.abspath(f))
log = []
if not shutil.which("ffprobe"):
    subprocess.run("sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg", shell=True, check=False)
def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", p]).decode().strip())
def gaps(p):
    r = subprocess.run(["ffmpeg", "-nostats", "-i", p, "-af", "silencedetect=noise=-48dB:d=0.4", "-f", "null", "-"], capture_output=True, text=True)
    s = re.findall(r"silence_start: ([0-9.]+)", r.stderr)
    e = re.findall(r"silence_end: ([0-9.]+)", r.stderr)
    return [(float(a), float(b)) for a, b in zip(s, e)]
try:
    cur = f
    log.append("input duration %.1f s" % dur(f))
    for k in range(3):
        d = dur(cur)
        gs = [g for g in gaps(cur) if g[0] > 3 and g[1] < d - 6]
        log.append("pass %d gaps: %s" % (k, gs))
        if not gs:
            break
        a, b = gs[0]
        nxt = os.path.join(out_dir, "fix%d.mp3" % k)
        flt = "[0:a]atrim=0:%.3f,asetpts=PTS-STARTPTS[x];[0:a]atrim=start=%.3f,asetpts=PTS-STARTPTS[y];[x][y]acrossfade=d=1.5:c1=tri:c2=tri[o]" % (a, b)
        subprocess.run(["ffmpeg", "-y", "-i", cur, "-filter_complex", flt, "-map", "[o]", "-b:a", "320k", nxt], check=True, capture_output=True)
        log.append("removed silence %.1f-%.1f s" % (a, b))
        cur = nxt
    if cur != f:
        os.replace(cur, f)
    d = dur(f)
    log.append("final duration %.1f s, remaining gaps: %d" % (d, len([g for g in gaps(f) if g[0] > 3 and g[1] < d - 6])))
except Exception:
    log.append("ERROR " + traceback.format_exc())
open(os.path.join(out_dir, "repair.txt"), "w").write(chr(10).join(log))
print(chr(10).join(log))
