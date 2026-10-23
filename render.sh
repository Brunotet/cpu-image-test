#!/usr/bin/env bash
set -u
mkdir -p out
BIN=stable-diffusion.cpp/build/bin/sd-cli
[ -x "$BIN" ] || BIN=stable-diffusion.cpp/build/bin/sd
DIFF=$(cat models/diffusion_path.txt)
LLM=$(cat models/llm_path.txt)
VAE=$(cat models/vae_path.txt)
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for size in 512 1024; do
  s=$(date +%s)
  timeout 120m "$BIN" --diffusion-model "$DIFF" --vae "$VAE" --llm "$LLM" -p "$PROMPT" --cfg-scale 1.0 --steps 8 -H $size -W $size -t "$(nproc)" -o out/test_$size.png -v 2>&1 | tail -n 30
  e=$(date +%s)
  echo "$size x $size: $((e-s)) seconds (model: $DIFF)" | tee -a out/timing.txt
  if [ -f out/test_$size.png ]; then
    python3 -c "from PIL import Image; Image.open('out/test_$size.png').convert('RGB').save('out/test_$size.jpg', quality=88)"
  fi
  git add out
  git commit -m "render $size" || true
  git pull --rebase -q || true
  git push || true
done
