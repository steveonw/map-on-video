#!/usr/bin/env python3
"""Draft narration from plan.json with a local TTS -> narration.wav + Audacity labels.

Works like the Read Aloud app: each sentence is synthesized separately, joined with
silence, and the label file records each sentence's exact start/end (computed from
sample counts, so it is exact by construction). The renderer reads both directly.

  python narrate.py plan.json --model-dir voices/kokoro-gpu-v1-0 --voice af_heart
  python narrate.py plan.json --model-dir models/kitten-micro-0.8 --voice 0
  python narrate.py plan.json --model-dir models/vits-piper-en_US-amy-medium
  python narrate.py --list-voices --model-dir voices/kokoro-gpu-v1-0
  python narrate.py plan.json --model-dir voices/kokoro-gpu-v1-0 --sample 8   # measure the pace

Pace: every run prints words per minute (while speaking, and with pauses) and, for the
whole plan, the projected length. --sample N voices only the first N lines (into the
cache, so the full run reuses them), prints the pace and the projected length of the
whole script, and writes no audio files: use it to size the script before writing it all.

Engines (picked from what is in --model-dir):
  * Kokoro v1.0 (onnx-community layout: onnx/model.onnx, voices/*.bin, tokenizer.json),
    the Read Aloud "Kokoro" voice: runs on CPU with onnxruntime + espeak phonemes.
    pip install onnxruntime espeakng-loader phonemizer-fork numpy
  * sherpa-onnx packages (model.onnx/.int8.onnx + tokens.txt [+ voices.bin] + espeak-ng-data):
    Kitten (needs sherpa-onnx 1.13.x), Kokoro (sherpa export), Piper/VITS (Amy, Lessac).
    pip install sherpa-onnx==1.13.4 numpy

Pauses: --gap after each sentence (Read Aloud's sentence pause), scene changes get
gap + 0.4 s (Read Aloud's paragraph pause); a line can set "pause_after": seconds,
e.g. 4 after a quiz question. --speed 1.0 = normal.

Several voices (dialogue, characters): give plan.json a "cast" and put "speaker" on a
line (that line only) or a scene (its default). Untagged lines use "narrator" from the
cast, or --voice. A cast entry is one voice, or one per engine:
  "cast": {"narrator": "af_heart", "student": {"kokoro": "am_adam", "kitten": 3}}
Unknown speakers stop before any audio is made. Each speaker is level-matched to the
others (one gain per speaker, so natural emphasis inside a voice is kept); --no-level skips it.
Kokoro British voices (bf_*, bm_*) use British pronunciation.

Cache: every sentence is kept in --cache (default tts_cache/ next to plan.json), keyed by
code version, engine, model, voice, speed and text, so after an edit only changed lines are
re-voiced (like Read Aloud's Render / Update). Each run lists the lines it re-voiced.
"""
import argparse, hashlib, json, re, sys, time, wave
from pathlib import Path
import numpy as np

CACHE_VERSION = 3          # bump when phoneme rules or synthesis change, so old audio is not reused
WARN = []


class KokoroV1:
    """Kokoro-82M v1.0 ONNX (same model/voices as Read Aloud's GPU voice), on CPU."""
    def __init__(self, d, threads):
        import onnxruntime as ort, espeakng_loader, os
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        from phonemizer.backend import EspeakBackend
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        os.environ['ESPEAK_DATA_PATH'] = espeakng_loader.get_data_path()
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        so = ort.SessionOptions(); so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(d / 'onnx' / 'model.onnx'), so, providers=['CPUExecutionProvider'])
        self.vocab = json.load(open(d / 'tokenizer.json'))['model']['vocab']
        self.voices_dir = d / 'voices'
        self.speakers = [s['name'] for s in json.load(open(d / 'voice.json')).get('speakers', [])] \
            if (d / 'voice.json').exists() else []
        self.names = sorted(p.stem for p in self.voices_dir.glob('*.bin'))
        self.backend = lambda lang: EspeakBackend(lang, preserve_punctuation=True, with_stress=True,
                                                  language_switch='remove-flags')
        self.espeak = {}
        self.sample_rate = 24000
        self.kind = 'kokoro'
        self.default = 'af_heart' if 'af_heart' in self.names else self.names[0]
        self.model_file = d / 'onnx' / 'model.onnx'

    def resolve(self, voice):
        """Voice name, or Read Aloud speaker number (needs its voice.json) -> file name, else None."""
        v = str(voice)
        if v.isdigit() and self.speakers and int(v) < len(self.speakers):
            first = self.speakers[int(v)].split(' (')[0].lower()
            return next((n for n in self.names if n.split('_', 1)[-1] == first), None)
        return v if v in self.names else None

    def voice_file(self, voice):
        return np.fromfile(self.voices_dir / f'{voice}.bin', dtype=np.float32).reshape(-1, 256)

    def phonemes(self, text, voice=''):
        text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
        lang = 'en-gb' if voice[:1] == 'b' else 'en-us'          # bf_/bm_ voices are British
        if lang not in self.espeak: self.espeak[lang] = self.backend(lang)
        ps = self.espeak[lang].phonemize([text], strip=True)[0]
        ps = (ps.replace('ʲ', 'j').replace('r', 'ɹ').replace('x', 'k').replace('ɬ', 'l'))
        ps = re.sub(r'(?<=[a-zɹː])(?=hˈʌndɹɪd)', ' ', ps)
        ps = re.sub(r' z(?=[;:,.!?¡¿—…"«»“” ]|$)', 'z', ps)
        ps = re.sub(r'(?<=nˈaɪn)ti(?!ː)', 'di', ps)
        return ps.strip()

    def say(self, text, voice, speed):
        ps = self.phonemes(text, voice)
        ids = [self.vocab[c] for c in ps if c in self.vocab]
        dropped = len(ps) - len(ids)
        if dropped > max(2, len(ps) // 20):
            WARN.append(f'{dropped} sounds dropped (unknown to Kokoro) in "{text[:50]}"; respell it')
        if len(ids) > 510:
            WARN.append(f'too long for Kokoro, end cut off: "{text[:50]}"; split the sentence')
            ids = ids[:510]
        style = self.voice_file(voice)[min(len(ids), 509)][None, :]
        wav = self.sess.run(None, {'input_ids': np.array([[0, *ids, 0]], dtype=np.int64),
                                   'style': style.astype(np.float32),
                                   'speed': np.array([speed], dtype=np.float32)})[0]
        return wav.reshape(-1).astype(np.float32)


class Sherpa:
    """sherpa-onnx package: Kitten, Kokoro (sherpa export) or Piper/VITS."""
    def __init__(self, d, threads):
        import sherpa_onnx as s
        model = next(p for p in (d / 'model.onnx', d / 'model.int8.onnx', *sorted(d.glob('*.onnx'))) if p.exists())
        mc = s.OfflineTtsModelConfig(num_threads=threads, provider='cpu')
        data = str(d / 'espeak-ng-data') if (d / 'espeak-ng-data').exists() else ''
        if (d / 'voices.bin').exists():
            common = dict(model=str(model), voices=str(d / 'voices.bin'), tokens=str(d / 'tokens.txt'), data_dir=data)
            if 'kokoro' in d.name.lower():
                mc.kokoro = s.OfflineTtsKokoroModelConfig(**common); self.kind = 'kokoro'
            else:                                   # Kitten; sherpa-onnx 2.x wants a lexicon file instead
                mc.kitten = s.OfflineTtsKittenModelConfig(**common); self.kind = 'kitten'
        else:
            mc.vits = s.OfflineTtsVitsModelConfig(model=str(model), tokens=str(d / 'tokens.txt'), data_dir=data)
            self.kind = 'vits'
        self.tts = s.OfflineTts(s.OfflineTtsConfig(model=mc, max_num_sentences=1))
        self.sample_rate = self.tts.sample_rate
        self.names = [str(i) for i in range(self.tts.num_speakers)]
        self.default, self.model_file = '0', model

    def resolve(self, voice):
        """Speaker number -> itself if this model has it, else None (sherpa voices are numbered)."""
        v = str(voice)
        return v if v in self.names else None

    def say(self, text, voice, speed):
        return np.asarray(self.tts.generate(text, sid=int(voice or 0), speed=speed).samples, dtype=np.float32)


def count_words(text):
    return len(re.findall(r"[\w'-]+", text))


def pace(words, speech_s, total_s):
    """Words per minute while speaking and with pauses (the number to size a script by)."""
    return (f'{words} words: {words / max(speech_s, 1e-9) * 60:.0f} wpm while speaking, '
            f'{words / max(total_s, 1e-9) * 60:.0f} wpm with pauses')


def load_engine(d, threads):
    d = Path(d)
    return KokoroV1(d, threads) if (d / 'onnx' / 'model.onnx').exists() else Sherpa(d, threads)


def resolve_voices(plan, eng, default):
    """Voice for every line from the cast (line "speaker" > scene "speaker" > narrator)."""
    cast = plan.get('cast', {})
    def pick(role):
        v = cast[role]
        if isinstance(v, dict):
            if eng.kind not in v:
                sys.exit(f'cast "{role}" has no voice for the {eng.kind} engine')
            v = v[eng.kind]
        return str(v)
    base = default if default is not None else (pick('narrator') if 'narrator' in cast else eng.default)
    out, bad = [], []
    for si, sc in enumerate(plan['scenes']):
        for li, ln in enumerate(sc['lines']):
            role = ln.get('speaker', sc.get('speaker'))
            if role is None: out.append(('narrator', base)); continue
            if role not in cast: bad.append(f'S{si + 1}.{li + 1} speaker "{role}"'); continue
            out.append((role, pick(role)))
    names = {v: eng.resolve(v) for _, v in out}
    bad += [f'voice "{v}" ({r})' for r, v in set(out) if names[v] is None]
    if bad:
        sys.exit('not in the cast or not a voice of this model: ' + '; '.join(sorted(set(bad)))
                 + f'\n  voices here: {", ".join(eng.names[:12])}{" ..." if len(eng.names) > 12 else ""}')
    return [(r, names[v]) for r, v in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plan', type=Path, nargs='?')
    ap.add_argument('--model-dir', required=True)
    ap.add_argument('--voice', help='narrator voice name (af_heart) or speaker number; default: cast "narrator" or 0')
    ap.add_argument('--speed', type=float, default=1.0)
    ap.add_argument('--gap', type=float, default=0.45, help='seconds after each sentence')
    ap.add_argument('--scene-gap', type=float, help='seconds between scenes (default gap + 0.4)')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--out', default='narration.wav'); ap.add_argument('--labels', default='labels.txt')
    ap.add_argument('--cache', type=Path, help='sentence cache folder (default tts_cache next to plan.json)')
    ap.add_argument('--no-level', action='store_true', help='do not level-match speakers')
    ap.add_argument('--list-voices', action='store_true')
    ap.add_argument('--sample', type=int, metavar='N',
                    help='voice only the first N lines, print the pace, write no audio files')
    a = ap.parse_args()
    eng = load_engine(a.model_dir, a.threads)
    if a.list_voices:
        print(', '.join(eng.names)); return
    plan = json.loads(a.plan.read_text(encoding='utf-8'))
    base = a.plan.resolve().parent
    voices = resolve_voices(plan, eng, a.voice)
    cache = a.cache or base / 'tts_cache'; cache.mkdir(parents=True, exist_ok=True)
    mf = Path(eng.model_file)
    model_id = f'{Path(a.model_dir).resolve().name}:{mf.stat().st_size}'     # same name, other weights -> new id
    scene_gap = a.scene_gap if a.scene_gap is not None else a.gap + 0.4
    sr = eng.sample_rate
    parts, labels, n, t0, made, reused, k, spoken = [], [], 0, time.time(), 0, 0, 0, []
    revoiced, nwords, speech = [], 0, 0
    all_words = sum(count_words(ln['text']) for sc in plan['scenes'] for ln in sc['lines'])
    for si, sc in enumerate(plan['scenes']):
        if a.sample and k >= a.sample: break
        for li, ln in enumerate(sc['lines']):
            if a.sample and k >= a.sample: break
            role, voice = voices[k]; k += 1
            key = hashlib.sha1(f'{CACHE_VERSION}|{eng.kind}|{model_id}|{voice}|{a.speed}|{ln["text"]}'
                               .encode()).hexdigest()[:20]
            cf = cache / f'{key}.npy'
            if cf.exists():
                audio = np.load(cf); reused += 1
            else:
                audio = eng.say(ln['text'], voice, a.speed); made += 1
                np.save(cache / f'{key}.tmp.npy', audio); (cache / f'{key}.tmp.npy').replace(cf)
                revoiced.append(f'S{si + 1}.{li + 1}  {ln["text"][:70]}')
            if not len(audio) or np.abs(audio).max() < 1e-3:
                sys.exit(f'no speech came out for S{si + 1}.{li + 1}: "{ln["text"][:60]}"')
            nwords += count_words(ln['text']); speech += len(audio)
            labels.append((n / sr, (n + len(audio)) / sr, ln['text']))
            spoken.append((len(parts), role)); parts.append(audio); n += len(audio)
            gap = ln.get('pause_after', scene_gap if li == len(sc['lines']) - 1 else a.gap)
            parts.append(np.zeros(int(gap * sr), np.float32)); n += int(gap * sr)
    for w in dict.fromkeys(WARN): print('  warning:', w)
    if a.sample:                                   # pace check only: no audio files written
        wpm = nwords / max(n / sr, 1e-9) * 60
        print(f'sample of {k} lines, {made} voiced, {reused} from cache; {pace(nwords, speech / sr, n / sr)}')
        print(f'whole script: {all_words} words -> about {all_words / wpm:.1f} min at this pace')
        return
    roles = {r for _, r in spoken}
    if len(roles) > 1 and not a.no_level:          # one gain per speaker toward the common level
        db = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
        level = {r: np.median([db(parts[i]) for i, rr in spoken if rr == r]) for r in roles}
        target = np.median(list(level.values()))
        gains = {r: 10 ** ((target - level[r]) / 20) for r in roles}
        for i, r in spoken: parts[i] = parts[i] * gains[r]
        print('level-matched: ' + ', '.join(f'{r} {20 * np.log10(g):+.1f} dB' for r, g in sorted(gains.items())))
    pcm = np.concatenate(parts)
    peak = np.abs(pcm).max()
    if peak > 0.89: pcm = pcm * (0.89 / peak)      # keep 1 dB of headroom, never clip
    with wave.open(str(base / a.out), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())
    (base / a.labels).write_text(''.join(f'{s:.6f}\t{e:.6f}\t{t}\n' for s, e, t in labels), encoding='utf-8')
    took = time.time() - t0
    cast = sorted({f'{r}={v}' for r, v in voices})
    print(f'wrote {a.out} ({n / sr:.1f}s, {len(labels)} sentences, {sr} Hz) and {a.labels}; '
          f'{made} voiced, {reused} from cache, {took:.1f}s; voices: {", ".join(cast)}')
    print(f'pace: {pace(nwords, speech / sr, n / sr)}; length {n / sr / 60:.1f} min')
    if revoiced:
        print(f're-voiced {len(revoiced)} line(s):')
        for r in revoiced[:40]: print('  ', r)
        if len(revoiced) > 40: print(f'   ... and {len(revoiced) - 40} more')


if __name__ == '__main__':
    main()
