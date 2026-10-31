#!/usr/bin/env python3
"""Listen-free narration check: does the audio match plan.json, and is it clear?

  python check_audio.py plan.json --asr-dir models/sherpa-onnx-zipformer-small-en-2023-06-26

Uses the plan's "audio" + "timestamps" (Audacity labels, SRT, VTT or JSON; any audio format
ffmpeg reads; "audio_offset" honoured). Each plan line is found in the timestamps and a small
speech recognizer transcribes that stretch of audio, which is compared with the PLAN text, so
narration made from an older script is caught. Also: silence, overlaps, loudness, peak, pauses,
quiz think time and, with several speakers, each speaker's pitch and loudness.
Every PROBLEM line is a failure (exit code 1); "check" lines are for review. The recognizer is a
proxy, not a listener: it can
mishear clear speech (single-letter math names like "x" -> "ex" are fine to ignore) and miss
unnatural speech. Respell a word only when a real word is consistently misheard.
ASR model (about 100 MB): sherpa-onnx GitHub release "asr-models",
sherpa-onnx-zipformer-small-en-2023-06-26.tar.bz2.  pip install sherpa-onnx numpy; needs ffmpeg.
"""
import argparse, difflib, json, re, subprocess, sys
from pathlib import Path
import numpy as np

SR = 16000
QUIZ = re.compile(r'quiz|test yourself|question|your turn|pause|think|try it', re.I)


def read_timestamps(path):
    """Audacity labels / SRT / VTT / JSON -> [(start, end, text)] (same as render_video.py)."""
    raw = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.json':
        d = json.loads(raw)
        d = d.get('segments', d.get('sentences', d)) if isinstance(d, dict) else d
        return [(float(e['start']), float(e['end']), e.get('text', '')) for e in d]
    def sec(t):
        h, m, s = (['0'] + t.replace(',', '.').split(':'))[-3:]
        return int(h) * 3600 + int(m) * 60 + float(s)
    if '-->' in raw:
        out = []
        for block in re.split(r'\n\s*\n', raw.strip()):
            ls = [l for l in block.splitlines() if l.strip()]
            for k, l in enumerate(ls):
                if '-->' in l:
                    a, b = [x.strip().split()[0] for x in l.split('-->')]
                    out.append((sec(a), sec(b), ' '.join(ls[k + 1:])))
                    break
        return out
    out = []
    for l in raw.splitlines():
        p = l.split('\t')
        if len(p) >= 2 and not l.startswith('\\'):
            out.append((float(p[0]), float(p[1]), p[2] if len(p) > 2 else ''))
    return out


def norm_text(s):
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def pitch(seg):
    """Median voice pitch in Hz (autocorrelation on loud 40 ms frames), 0 if unvoiced."""
    f, out = int(.04 * SR), []
    lo, hi = int(SR / 400), int(SR / 70)
    for i in range(0, len(seg) - f, f):
        w = seg[i:i + f] - seg[i:i + f].mean()
        if np.sqrt((w ** 2).mean()) < .02: continue
        ac = np.correlate(w, w, 'full')[f - 1:]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > .3 * ac[0]: out.append(SR / lag)
    return float(np.median(out)) if out else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plan', type=Path); ap.add_argument('--asr-dir', required=True)
    ap.add_argument('--threads', type=int, default=2)
    args = ap.parse_args()
    import sherpa_onnx
    base = args.plan.resolve().parent; plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if not plan.get('audio') or not plan.get('timestamps'):
        sys.exit('plan needs "audio" and "timestamps" to check')
    d = Path(args.asr_dir); enc = sorted(d.glob('encoder*.int8.onnx')) or sorted(d.glob('encoder*.onnx'))
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(enc[0]), decoder=str(sorted(d.glob('decoder*.onnx'))[0]),
        joiner=str((sorted(d.glob('joiner*.int8.onnx')) or sorted(d.glob('joiner*.onnx')))[0]),
        tokens=str(d / 'tokens.txt'), num_threads=args.threads)
    off = float(plan.get('audio_offset', 0))
    pcm = subprocess.run(['ffmpeg', '-v', 'error', *(['-ss', f'{off}'] if off else []),
                          '-i', str(base / plan['audio']), '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    labels = read_timestamps(base / plan['timestamps'])
    lines = [(ln.get('speaker', sc.get('speaker', 'narrator')), ln['text'], ln)
             for sc in plan['scenes'] for ln in sc['lines']]
    dur, problems = len(x) / SR, []
    if not labels: sys.exit('no entries in the timestamp file')
    if any(b[0] < p[1] - 1e-3 or b[0] < p[0] for p, b in zip(labels, labels[1:])):
        problems.append('timestamps overlap or go backwards')
    if labels[-1][1] > dur + .05:
        problems.append(f'last timestamp {labels[-1][1]:.2f}s is past the audio end {dur:.2f}s')

    # find every plan line in the timestamps, in order (extra entries such as spoken titles are fine)
    found, j = [], 0
    for k, (_, text, _) in enumerate(lines):
        best, br = None, 0.0
        for c in range(j, min(len(labels), j + 20)):
            r = difflib.SequenceMatcher(None, norm_text(text), norm_text(labels[c][2])).ratio()
            if r > br: best, br = c, r
        if best is None or br < 0.6:
            problems.append(f'line {k + 1} is not in the narration (out of date?): "{text[:50]}"')
            found.append(None); continue
        if br < 0.97:
            problems.append(f'line {k + 1} was narrated from different text: "{labels[best][2][:40]}" '
                            f'vs plan "{text[:40]}"; re-narrate')
        found.append(best); j = best + 1

    words = lambda s: re.sub(r'[^a-z ]+', ' ', s.lower().replace('-', ' ')).split()
    tot = err = 0; loud = []; by_role = {}; misheard = []
    for k, ((role, text, ln), c) in enumerate(zip(lines, found)):
        if c is None: continue
        s0, s1, _ = labels[c]
        seg = x[int(s0 * SR):int(s1 * SR)]
        db = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9) if len(seg) else -120
        loud.append(db)
        if db < -50: problems.append(f'line {k + 1} is silent: "{text[:50]}"'); continue
        by_role.setdefault(role, []).append((db, seg))
        st = rec.create_stream(); st.accept_waveform(SR, seg); rec.decode_stream(st)
        ref, hyp = words(text), words(st.result.text)
        e = len(ref) - sum(m.size for m in difflib.SequenceMatcher(None, ref, hyp).get_matching_blocks())
        tot += len(ref); err += e
        if ref and e / len(ref) > 0.2:
            msg = f'line {k + 1}: "{text[:55]}"  heard as  "{st.result.text.lower()[:55]}"'
            if e / len(ref) > 0.5: problems.append(f'mostly unrecognisable {msg}')
            else: misheard.append(msg)
        nxt = labels[c + 1][0] if c + 1 < len(labels) else dur
        prev = lines[k - 1][1] if k else ''
        if text.rstrip().endswith('?') and (QUIZ.search(text) or QUIZ.search(prev)):
            print(f'  quiz question at {s0:.1f}s -> {nxt - s1:.1f}s to think')
            if nxt - s1 < 4: problems.append(f'line {k + 1}: quiz think time {nxt - s1:.1f}s; needs 4 s or more')

    miss = err / max(tot, 1) * 100
    gaps = [labels[i + 1][0] - labels[i][1] for i in range(len(labels) - 1)]
    print(f'{len(found)} plan lines, {len(labels)} timestamps; recognizer missed {miss:.1f}% of words '
          '(a rough clarity signal; usually under 8% for clear speech)')
    print(f'loudness spread {np.std(loud):.2f} dB; peak {20 * np.log10(np.abs(x).max() + 1e-9):.1f} dBFS')
    if np.abs(x).max() > .999: problems.append('audio clips (peak at full scale)')
    if gaps: print(f'pauses: min {min(gaps):.2f}s, typical {np.median(gaps):.2f}s, max {max(gaps):.2f}s')
    if miss > 8: problems.append(f'recognizer missed {miss:.1f}% of words; see the check lines')
    for m in misheard: print('  check (often a recognizer quirk, fix only real mispronunciations):', m)
    if len(by_role) > 1:                               # several voices: did they really differ?
        print('voices (a role change should move pitch or loudness):')
        for role, v in by_role.items():
            ps = [p for p in (pitch(s) for _, s in v) if p]
            print(f'  {role:12s} {len(v):3d} lines, {np.mean([l for l, _ in v]):6.1f} dB, '
                  f'pitch {np.median(ps) if ps else 0:5.0f} Hz')
    for p in problems: print('PROBLEM:', p)
    print('OK: no problems' if not problems else f'{len(problems)} problems')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
