#!/usr/bin/env bash
# One-command setup for map-on-video: system packages, Python packages, native MapLibre, the Kokoro voice and the
# speech-check model. Safe to rerun: anything already in place is skipped. Ends with a self-check and prints the
# paths to pass as --narrate and --asr-dir.
#
#   bash tools/setup.sh                      # voices in ./voices, map cache in ~/.cache/routevid
#   bash tools/setup.sh --voices DIR --cache DIR --no-asr
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
VOICES="$here/voices"; CACHE="$HOME/.cache/routevid"; ASR=1
while [ $# -gt 0 ]; do
  case "$1" in
    --voices) VOICES="$2"; shift 2 ;;
    --cache) CACHE="$2"; shift 2 ;;
    --no-asr) ASR=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
say() { printf '\n== %s\n' "$*"; }

say "system packages (xvfb, libopengl0, ffmpeg)"
need=()
command -v xvfb-run >/dev/null || need+=(xvfb)
command -v ffmpeg >/dev/null || need+=(ffmpeg)
ldconfig -p 2>/dev/null | grep -q libOpenGL.so.0 || need+=(libopengl0)
if [ ${#need[@]} -eq 0 ]; then echo "all present"
elif command -v apt-get >/dev/null; then
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  $SUDO apt-get install -y "${need[@]}" >/dev/null 2>&1 || { $SUDO apt-get update >/dev/null 2>&1 && $SUDO apt-get install -y "${need[@]}" >/dev/null; }
  echo "installed: ${need[*]}"
else echo "missing ${need[*]} and no apt-get: install them yourself" >&2; fi
command -v node >/dev/null && command -v npm >/dev/null || { echo "node and npm are required" >&2; exit 1; }

say "python packages"
pip install -q --break-system-packages -r "$here/requirements.txt" 2>&1 | grep -v -i "warning: running pip as" || true

say "native MapLibre 6.4.1 -> $CACHE/node3"
mkdir -p "$CACHE/node3"
pkg="$CACHE/node3/node_modules/@maplibre/maplibre-gl-native/package.json"
if [ -f "$pkg" ] && grep -q '"version": "6.4.1"' "$pkg"; then echo "present"
else npm install --prefix "$CACHE/node3" @maplibre/maplibre-gl-native@6.4.1 --silent; echo "installed"; fi

fetch() {  # url dest: download once, to a temp name first so an interrupted download is never mistaken for a good one
  [ -s "$2" ] && return 0
  mkdir -p "$(dirname "$2")"; curl -sSfL -o "$2.part" "$1" && mv "$2.part" "$2"
}
say "Kokoro v1.0 voice -> $VOICES/kokoro-v1 (model.onnx must be in onnx/)"
HF=https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main
K="$VOICES/kokoro-v1"
[ -f "$K/model.onnx" ] && [ ! -f "$K/onnx/model.onnx" ] && { mkdir -p "$K/onnx"; mv "$K/model.onnx" "$K/onnx/"; echo "moved a misplaced model.onnx into onnx/"; }
fetch "$HF/onnx/model.onnx" "$K/onnx/model.onnx"
fetch "$HF/tokenizer.json" "$K/tokenizer.json"
fetch "$HF/voices/af_heart.bin" "$K/voices/af_heart.bin"
echo "ok ($(du -sh "$K" | cut -f1))"

if [ "$ASR" = 1 ]; then
  say "speech-check model -> $VOICES/asr"
  A="$VOICES/asr/sherpa-onnx-zipformer-small-en-2023-06-26"
  if [ -f "$A/tokens.txt" ]; then echo "present"
  else
    mkdir -p "$VOICES/asr"
    fetch https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-small-en-2023-06-26.tar.bz2 "$VOICES/asr/asr.tar.bz2"
    tar xjf "$VOICES/asr/asr.tar.bz2" -C "$VOICES/asr" && rm -f "$VOICES/asr/asr.tar.bz2"; echo "installed"
  fi
fi

say "self-check: voice one word"
tmp="$(mktemp -d)"
printf '{"title":"check","scenes":[{"title":"c","lines":[{"text":"Ready."}]}]}' > "$tmp/plan.json"
if python3 "$here/tools/narrate.py" "$tmp/plan.json" --model-dir "$K" --voice af_heart >/dev/null 2>"$tmp/err" && [ -s "$tmp/narration.wav" ]; then
  echo "voice ok"
else echo "voice check FAILED:"; tail -5 "$tmp/err"; rm -rf "$tmp"; exit 1; fi
rm -rf "$tmp"

say "ready"
echo "  --narrate $K"
[ "$ASR" = 1 ] && echo "  --asr-dir $A (for tools/check_audio.py)"
echo "  --cache $CACHE"
