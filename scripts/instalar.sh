#!/usr/bin/env bash
# Prepara el entorno local de voz en ~/.local/share/narrador/: venv con Kokoro, Piper, faster-whisper
# y edge-tts, el modelo de Kokoro (~350 MB), voces de Piper y el modelo small de Whisper (~600 MB).
# Uso: scripts/instalar.sh [VOZ ...]   (por defecto es_ES-davefx-medium)
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="${XDG_DATA_HOME:-$HOME/.local/share}/narrador"
VENV="$RUNTIME/venv"
VOCES=("$@")
[ ${#VOCES[@]} -eq 0 ] && VOCES=(es_ES-davefx-medium)

mkdir -p "$RUNTIME/voces"
if [ ! -x "$VENV/bin/python" ]; then
  echo "· creando venv en $VENV"
  python3 -m venv "$VENV"
fi
echo "· instalando kokoro-onnx, piper-tts, faster-whisper y edge-tts"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q kokoro-onnx piper-tts faster-whisper edge-tts

KOKORO="$RUNTIME/kokoro"
mkdir -p "$KOKORO"
for archivo in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ -s "$KOKORO/$archivo" ]; then
    echo "· $archivo de Kokoro ya descargado"
  else
    echo "· descargando $archivo de Kokoro"
    curl -sSfL -o "$KOKORO/$archivo.part" \
      "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$archivo"
    mv "$KOKORO/$archivo.part" "$KOKORO/$archivo"
  fi
done

echo "· preparando el modelo small de Whisper"
"$VENV/bin/python" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='$RUNTIME/whisper')"

for voz in "${VOCES[@]}"; do
  if [ -f "$RUNTIME/voces/$voz.onnx" ]; then
    echo "· voz $voz ya instalada"
  else
    echo "· descargando voz $voz"
    (cd "$RUNTIME" && "$VENV/bin/python" -m piper.download_voices "$voz" --data-dir "$RUNTIME/voces")
  fi
done

command -v pw-play >/dev/null || echo "aviso: no encuentro pw-play; cambia \"reproductor\" en $RUNTIME/config.json (p. ej. aplay)"
command -v pw-record >/dev/null || echo "aviso: no encuentro pw-record; Ío no podrá escucharte"
echo "listo. Prueba: $RAIZ/bin/narrador prueba"
