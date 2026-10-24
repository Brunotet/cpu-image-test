#!/usr/bin/env bash
set -u
mkdir -p out
BIN=stable-diffusion.cpp/build/bin/sd-cli
[ -x "$BIN" ] || BIN=stable-diffusion.cpp/build/bin/sd
DIFF=$(cat models/diffusion_path.txt)
LLM=$(cat models/llm_path.txt)
VAE=$(cat models/vae_path.txt)
s=$(date +%s)
timeout 150m "$BIN" --diffusion-model "$DIFF" --vae "$VAE" --llm "$LLM" -p "$PROMPT" --cfg-scale 1.0 --steps 8 -H 1024 -W 1024 -t "$(nproc)" -o out/img_$IDX.png -v 2>&1 | tail -n 5
e=$(date +%s)
echo "img_$IDX: $((e-s)) seconds" > out/time_$IDX.txt
cat out/time_$IDX.txt
if [ -f out/img_$IDX.png ]; then
  python3 -c "from PIL import Image; Image.open('out/img_$IDX.png').convert('RGB').save('out/img_$IDX.jpg', quality=88)"
fi
