import subprocess, json, os, time, threading, shutil, math
from collections import deque

T0 = time.time()

def log(*a):
    print(*a, flush=True)

def stamp(m):
    log('[%4ds] %s' % (round(time.time() - T0), m))

UVENV = {'UV_CACHE_DIR': '/tmp/uvcache', 'UV_LINK_MODE': 'copy', 'UV_HTTP_TIMEOUT': '300'}

def sh(cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=e)
    return r.returncode, (r.stdout + r.stderr)

# ======================= CUE SHEET (edit this to make music) =======================
# name | caption (overall style) | duration (total seconds) | bpm + keyscale (keep fixed for long tracks)
# seeds: starting points (101 is deliberately not used)
# parts (optional): list of {seconds, caption, gain_db} for exact section timing and per-section volume
# tracks longer than 120 s without parts are split into about 75 s pieces and joined with crossfades
CUES = [
    {'name': 'cinematic_arc_3part', 'caption': 'cinematic orchestral underscore, warm felt piano, soft legato strings, spacious natural reverb, studio-quality recording, wide stereo image, clean polished mix', 'duration': 180, 'bpm': 70, 'keyscale': 'D minor', 'seeds': [202], 'parts': [
        {'seconds': 60, 'caption': 'calm intro, solo felt piano, sparse and quiet', 'gain_db': -8},
        {'seconds': 60, 'caption': 'dramatic peak, powerful drums, brass, full orchestra, intense and epic', 'gain_db': 0},
        {'seconds': 60, 'caption': 'gentle resolution, warm pads, soft piano, slow fade out', 'gain_db': -7}]},
    {'name': 'lofi_150s', 'caption': 'lo-fi hip hop beat, mellow Rhodes electric piano chords, dusty vinyl-sampled drums, soft sub bass, relaxed swing groove, warm tape saturation, cozy late-night study mood, clean polished mix', 'duration': 150, 'bpm': 82, 'keyscale': 'F major', 'seeds': [303]},
]
XF = 4.0
HEAD_TRIM = 5.0
TAIL_TRIM = 10.0
STEPS = 50
GUIDANCE = 7.0
# ===================================================================================

log(sh('nvidia-smi --query-gpu=name,memory.total --format=csv')[1])
rc, o = sh('pip install -q uv 2>&1 | tail -2; uv --version')
rc, o = sh('git clone --depth 1 -q https://github.com/ACE-Step/ACE-Step-1.5.git /tmp/ace')
if rc != 0:
    log(o)
    raise SystemExit(1)

from huggingface_hub import snapshot_download
dl = {}
CK = '/tmp/ace/checkpoints'

def download(key, repo, sub):
    try:
        snapshot_download(repo_id=repo, local_dir=(CK + '/' + sub) if sub else CK)
        dl[key] = 'ok'
    except Exception as e:
        dl[key] = 'ERR ' + repr(e)[:200]
    stamp('download ' + key + ': ' + dl[key])

threads = []
for k, r, s in [('main', 'ACE-Step/Ace-Step1.5', ''), ('sft2b', 'ACE-Step/acestep-v15-sft', 'acestep-v15-sft')]:
    t = threading.Thread(target=download, args=(k, r, s))
    t.start()
    threads.append(t)

rc, o = sh('cd /tmp/ace && uv sync --python 3.12', UVENV)
stamp('uv sync rc ' + str(rc))
if rc != 0:
    log(o[-3500:])
    raise SystemExit(1)

CHK = r'''import torch
print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'gpus', torch.cuda.device_count())
'''
open('/tmp/chk.py', 'w').write(CHK)
rc, o = sh('cd /tmp/ace && uv run --no-sync python /tmp/chk.py', UVENV)
stamp('env check: ' + o.strip()[-120:])
if rc != 0 or 'cuda True' not in o:
    log(o[-2000:])
    raise SystemExit(1)
for t in threads:
    t.join()
if any(v != 'ok' for v in dl.values()):
    stamp('DOWNLOAD PROBLEM ' + str(dl))
    raise SystemExit(1)

SYNC = r'''import sys
sys.path.insert(0, '/tmp/ace')
from acestep.model_downloader import _sync_model_code_files, MAIN_MODEL_COMPONENTS, get_checkpoints_dir
d = get_checkpoints_dir()
for c in list(MAIN_MODEL_COMPONENTS) + ['acestep-v15-sft']:
    try:
        print(c, _sync_model_code_files(c, d))
    except Exception as e:
        print(c, 'sync err', repr(e)[:200])
'''
open('/tmp/sync.py', 'w').write(SYNC)
sh('cd /tmp/ace && uv run --no-sync python /tmp/sync.py', UVENV)

PATCH = r'''import sys
cur, new = sys.argv[1], sys.argv[2]
nl = chr(10)
p1 = '/tmp/ace/acestep/core/generation/handler/init_service_orchestrator.py'
old1 = '                else:' + nl + '                    self.dtype = torch.' + cur + nl
new1 = '                else:' + nl + '                    self.dtype = torch.' + new + nl
p2 = '/tmp/ace/acestep/core/generation/handler/memory_utils.py'
old2 = '                return torch.bfloat16' + nl + '            return torch.' + cur + nl
new2 = '                return torch.bfloat16' + nl + '            return torch.' + new + nl
for p, old, nw in [(p1, old1, new1), (p2, old2, new2)]:
    s = open(p).read()
    n = s.count(old)
    print(p, 'matches', n)
    if n != 1:
        print('PATCH FAILED')
        sys.exit(1)
    open(p, 'w').write(s.replace(old, nw))
print('PATCH OK ' + cur + ' -> ' + new)
'''
open('/tmp/patch.py', 'w').write(PATCH)
rc, o = sh('python /tmp/patch.py float16 float32')
stamp('float32 patch: ' + o.strip()[-100:])
if rc != 0:
    raise SystemExit(1)

# ---- expand cues into segment jobs (interior pieces are generated longer so faded edges can be cut off) ----
def expand(cue):
    total = cue['duration']
    parts = cue.get('parts')
    if not parts:
        n = 1 if total <= 120 else int(math.ceil(total / 75.0))
        parts = [{'seconds': total / float(n), 'caption': '', 'gain_db': 0} for _ in range(n)]
    segs = []
    last = len(parts) - 1
    for i, p in enumerate(parts):
        head = HEAD_TRIM if i > 0 else 0.0
        tail = TAIL_TRIM if i < last else 0.0
        keep = p['seconds'] + (XF if i < last else 0)
        cap = cue['caption']
        if p.get('caption'):
            cap = cap + ', ' + p['caption']
        if i > 0:
            cap = cap + ', continuation of the same piece'
        segs.append({'idx': i, 'gen_seconds': int(round(keep + head + tail)), 'head': head, 'tail': tail, 'gain': p.get('gain_db', 0), 'caption': cap})
    return segs

jobs = []
plan = {}
for cue in CUES:
    segs = expand(cue)
    multi = len(segs) > 1
    bpm = cue.get('bpm') or (80 if multi else None)
    key = cue.get('keyscale') or ('C major' if multi else '')
    for sd in cue.get('seeds', [202, 303, 404]):
        assert sd not in (101, 7777)
        plist = []
        for s in segs:
            jname = cue['name'] + '_seed' + str(sd) + '_p' + str(s['idx'])
            jobs.append({'job': jname, 'caption': s['caption'], 'bpm': bpm, 'keyscale': key, 'duration': s['gen_seconds'], 'seed': sd + s['idx'] * 11})
            plist.append({'job': jname, 'head': s['head'], 'tail': s['tail'], 'gain': s['gain']})
        plan[cue['name'] + '_seed' + str(sd)] = {'cue': cue['name'], 'seed': sd, 'parts': plist, 'req_sec': cue['duration']}
json.dump(jobs, open('/tmp/jobs.json', 'w'))
stamp('segments to generate: ' + str(len(jobs)))

GEN = r'''import os, sys, json, time, shutil
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)
sys.path.insert(0, '/tmp/ace')
import torch
from acestep.handler import AceStepHandler
from acestep.llm_inference import LLMHandler
from acestep.inference import GenerationParams, GenerationConfig, generate_music

ROOT = '/tmp/ace'
CKPT = ROOT + '/checkpoints'
OUT = '/tmp/gen_out'
PARTS = '/kaggle/working/parts'
os.makedirs(OUT, exist_ok=True)
os.makedirs(PARTS, exist_ok=True)
STEPS = int(os.environ['STEPS'])
GUID = float(os.environ['GUID'])
jobs = json.load(open('/tmp/jobs.json'))
T0 = time.time()

def stamp(m):
    print('[gen %4ds] %s' % (round(time.time() - T0), m), flush=True)

dit = AceStepHandler()
msg, ok = dit.initialize_service(project_root=ROOT, config_path='acestep-v15-sft', device='cuda', offload_to_cpu=False, offload_dit_to_cpu=False)
stamp('DiT ok=' + str(ok) + ' dtype=' + str(getattr(dit, 'dtype', None)))
if not ok:
    sys.exit(2)
llm = LLMHandler()
use_lm = False
for name, dev, dt in [('acestep-5Hz-lm-1.7B', 'cuda:1', torch.float32), ('acestep-5Hz-lm-1.7B', 'cuda:1', None)]:
    try:
        m2, ok2 = llm.initialize(checkpoint_dir=CKPT, lm_model_path=name, backend='pt', device=dev, offload_to_cpu=False, dtype=dt)
        stamp('LM ' + name + ' dtype=' + str(dt) + ' ok=' + str(ok2))
        if ok2:
            use_lm = True
            break
    except Exception as e:
        stamp('LM init exception ' + repr(e)[:200])

manifest = []
bad = 0
for j in jobs:
    try:
        params = GenerationParams(task_type='text2music', thinking=use_lm, use_cot_caption=use_lm, use_cot_language=use_lm, use_cot_metas=use_lm, caption=j['caption'], lyrics='[Instrumental]', instrumental=True, bpm=j.get('bpm'), keyscale=j.get('keyscale', ''), duration=j['duration'], inference_steps=STEPS, guidance_scale=GUID, shift=1.0, seed=j['seed'], vocal_language='en')
        config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[j['seed']], audio_format='flac')
        t = time.time()
        r = generate_music(dit, llm, params=params, config=config, save_dir=OUT)
        if not r.success:
            raise RuntimeError(str(r.error)[:300])
        path = PARTS + '/' + j['job'] + '.flac'
        shutil.copy(r.audios[0].get('path'), path)
        info = {'job': j['job'], 'seed': j['seed'], 'req_sec': j['duration'], 'gen_sec': round(time.time() - t, 1), 'path': path}
        manifest.append(info)
        stamp('OK ' + json.dumps(info))
    except Exception as e:
        bad += 1
        stamp('FAILED ' + j['job'] + ' ' + repr(e)[:300])
    json.dump(manifest, open('/kaggle/working/parts_manifest.json', 'w'), indent=1)
stamp('DONE segments=%d failed=%d' % (len(manifest), bad))
sys.exit(3 if bad else 0)
'''
open('/tmp/gen.py', 'w').write(GEN)

def run_gen():
    e = dict(os.environ)
    e.update(UVENV)
    e.update({'STEPS': str(STEPS), 'GUID': str(GUIDANCE)})
    p = subprocess.Popen('cd /tmp/ace && uv run --no-sync python /tmp/gen.py', shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=e)
    tail = deque(maxlen=50)
    for line in p.stdout:
        tail.append(line.rstrip()[:300])
        if '[gen' in line:
            log(line.rstrip()[:700])
    p.wait()
    if p.returncode != 0:
        log('--- last lines of generator output ---')
        log(chr(10).join(tail))
    return p.returncode

stamp('generating segments (2B sft float32, planner float32 on second GPU)')
run_gen()

# ---- trim fades, apply gains, crossfade, master, verify ----
import numpy as np

def probe_dur(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return None

def db_series(path):
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', '16000', '-'], capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.float32)
    n = len(x) // 16000
    out = []
    for i in range(n):
        seg = x[i * 16000:(i + 1) * 16000]
        out.append(round(20 * math.log10(max(float(np.sqrt(np.mean(seg * seg))), 1e-6)), 1))
    return out

def master(src, dst):
    af = 'areverse,silenceremove=start_periods=1:start_threshold=-55dB:start_duration=0.2,areverse,loudnorm=I=-16:TP=-1.5:LRA=11'
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-af', af, '-codec:a', 'libmp3lame', '-b:a', '320k', dst], capture_output=True, text=True)
    return r.returncode == 0

os.makedirs('/kaggle/working/final', exist_ok=True)
pm = {}
try:
    for m in json.load(open('/kaggle/working/parts_manifest.json')):
        pm[m['job']] = m
except Exception:
    pass
final = []
for key, pl in plan.items():
    try:
        parts = pl['parts']
        if not all(p['job'] in pm for p in parts):
            stamp('SKIP ' + key + ' (a segment failed)')
            continue
        n = len(parts)
        fulls = [probe_dur(pm[p['job']]['path']) for p in parts]
        kept = [fulls[i] - parts[i]['head'] - parts[i]['tail'] for i in range(n)]
        fc = ''
        for i in range(n):
            end = round(fulls[i] - parts[i]['tail'], 3)
            fc += '[' + str(i) + ':a]atrim=start=' + str(parts[i]['head']) + ':end=' + str(end) + ',asetpts=PTS-STARTPTS,volume=' + str(parts[i]['gain']) + 'dB[s' + str(i) + '];'
        prev = '[s0]'
        for i in range(1, n):
            lab = '[a' + str(i) + ']'
            fc += prev + '[s' + str(i) + ']acrossfade=d=' + str(XF) + ':c1=qsin:c2=qsin' + lab + ';'
            prev = lab
        fc = fc.rstrip(';')
        joined = '/kaggle/working/final/' + key + '.flac'
        cmd = ['ffmpeg', '-y', '-loglevel', 'error']
        for p in parts:
            cmd += ['-i', pm[p['job']]['path']]
        cmd += ['-filter_complex', fc, '-map', prev, '-c:a', 'flac', joined]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            stamp('STITCH FAILED ' + key + ' ' + r.stderr[-300:])
            continue
        boundaries = []
        acc = 0.0
        for i in range(1, n):
            acc += kept[i - 1]
            boundaries.append(round(acc - i * XF, 1))
        mp3 = '/kaggle/working/final/' + key + '.mp3'
        okm = master(joined, mp3)
        info = {'name': key, 'seed': pl['seed'], 'segments': n, 'req_sec': pl['req_sec'], 'joined_sec': round(probe_dur(joined) or 0, 1), 'mp3_sec': round(probe_dur(mp3) or 0, 1), 'mp3_ok': okm, 'crossfade_sec': XF if n > 1 else 0, 'head_trim': HEAD_TRIM, 'tail_trim': TAIL_TRIM, 'gains_db': [p['gain'] for p in parts], 'steps': STEPS, 'guidance': GUIDANCE, 'gen_sec_total': round(sum(pm[p['job']]['gen_sec'] for p in parts), 1), 'segment_seeds': [pm[p['job']]['seed'] for p in parts]}
        series = db_series(joined)
        info['loudness_db_per_10s'] = [round(float(np.mean(series[i:i + 10])), 1) for i in range(0, len(series), 10)]
        if boundaries:
            checks = []
            for b in boundaries:
                lo = max(int(b) - 3, 0)
                hi = min(int(b + XF) + 4, len(series))
                checks.append({'at_sec': b, 'db_1s_windows': series[lo:hi]})
            info['boundary_loudness'] = checks
        final.append(info)
        stamp('FINAL ' + json.dumps(info))
    except Exception as e:
        stamp('POST FAILED ' + key + ' ' + repr(e)[:300])
json.dump(final, open('/kaggle/working/final_manifest.json', 'w'), indent=1)
log(sh('ls -la /kaggle/working/final | head -30')[1])
stamp('TOTAL - session ends now')
