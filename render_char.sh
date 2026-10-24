#!/usr/bin/env bash
set -u
mkdir -p out
BIN=stable-diffusion.cpp/build/bin/sd-cli
[ -x "$BIN" ] || BIN=stable-diffusion.cpp/build/bin/sd
DIFF=$(cat models/diffusion_path.txt)
LLM=$(cat models/llm_path.txt)
VAE=$(cat models/vae_path.txt)
SIZE=${SIZE:-768}
NAME=${NAME:-char}
s=$(date +%s)
if [ "${MODE:-char}" = "char" ]; then
  timeout 150m "$BIN" --diffusion-model "$DIFF" --vae "$VAE" --llm "$LLM" -p "$PROMPT" --cfg-scale 1.0 --steps 4 --sampling-method euler -H $SIZE -W $SIZE -t "$(nproc)" -o out/$NAME.png -v 2>&1 | tail -n 8
else
  timeout 150m "$BIN" --diffusion-model "$DIFF" --vae "$VAE" --llm "$LLM" -r ref/char.png -p "$PROMPT" --cfg-scale 1.0 --steps 4 --sampling-method euler -H $SIZE -W $SIZE -t "$(nproc)" -o out/$NAME.png -v 2>&1 | tail -n 8
fi
e=$(date +%s)
echo "$NAME: $((e-s)) seconds" > out/time_$NAME.txt
cat out/time_$NAME.txt
if [ -f out/$NAME.png ]; then
  python3 -c "from PIL import Image; Image.open('out/$NAME.png').convert('RGB').save('out/$NAME.jpg', quality=90)"
fi
