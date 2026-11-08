import sys, re, json, subprocess, os
from pathlib import Path
# Gets the spoken text of a YouTube video without cookies: captions via youtube-transcript-api, else yt-dlp with other player clients.
vid = re.search(r'(?:shorts/|v=|youtu\.be/)([\w-]{11})', sys.argv[1]).group(1)
out = Path(sys.argv[2])
def save(lines, how):
    out.write_text(f"{sys.argv[1]}\n(via {how})\n" + "\n".join(lines) + "\n"); print("ok", vid, how, len(lines)); sys.exit(0)
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    t = api.fetch(vid, languages=['en', 'en-US', 'en-GB'])
    save([f"[{s.start:6.1f}] {s.text.strip()}" for s in t], 'youtube-transcript-api')
except Exception as e:
    print('yta failed', str(e)[:200])
for client in ('tv_embedded', 'web_embedded', 'mweb', 'ios', 'android_vr', 'web_safari'):
    d = Path('work_sub'); d.mkdir(exist_ok=True)
    for f in d.glob('*'): f.unlink()
    r = subprocess.run(['yt-dlp', '--skip-download', '--write-auto-subs', '--write-subs', '--sub-langs', 'en.*', '--sub-format', 'json3', '--extractor-args', f'youtube:player_client={client}', '-o', str(d / 's'), f'https://www.youtube.com/watch?v={vid}'], capture_output=True, text=True)
    files = list(d.glob('*.json3'))
    if files:
        data = json.loads(files[0].read_text())
        lines = []
        for ev in data.get('events', []):
            txt = ''.join(s.get('utf8', '') for s in ev.get('segs', []) if s).strip()
            if txt: lines.append(f"[{ev.get('tStartMs', 0)/1000:6.1f}] {txt}")
        if lines: save(lines, 'yt-dlp subs ' + client)
    print(client, 'failed', (r.stderr or '')[-150:].replace('\n', ' '))
out.write_text(f"{sys.argv[1]}\nFAILED: no captions reachable\n"); print('all failed')
