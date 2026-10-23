import os
from huggingface_hub import list_repo_files, hf_hub_download

os.makedirs('models', exist_ok=True)
files = list_repo_files('leejet/Z-Image-Turbo-GGUF')
print(files)
pick = None
for pref in ['Q4_K', 'Q4_0', 'Q5', 'Q3_K', 'Q8']:
    c = [f for f in files if f.endswith('.gguf') and pref in f]
    if c:
        pick = sorted(c)[0]
        break
print('diffusion model:', pick)
d = hf_hub_download('leejet/Z-Image-Turbo-GGUF', pick, local_dir='models')
l = hf_hub_download('unsloth/Qwen3-4B-Instruct-2507-GGUF', 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf', local_dir='models')
try:
    v = hf_hub_download('black-forest-labs/FLUX.1-schnell', 'ae.safetensors', local_dir='models')
except Exception as e:
    print('schnell vae failed, falling back:', e)
    v = hf_hub_download('Comfy-Org/z_image_turbo', 'split_files/vae/ae.safetensors', local_dir='models')
for name, p in [('diffusion', d), ('llm', l), ('vae', v)]:
    open('models/%s_path.txt' % name, 'w').write(os.path.abspath(p))
print('done')
