import os
from huggingface_hub import list_repo_files, hf_hub_download

os.makedirs('models', exist_ok=True)
gg = list_repo_files('leejet/FLUX.2-klein-4B-GGUF')
print(gg)
pick = None
for pref in ['Q4_K', 'Q4_0', 'Q5', 'Q8']:
    c = [f for f in gg if f.endswith('.gguf') and pref in f and 'base' not in f.lower()]
    if c:
        pick = sorted(c)[0]
        break
print('diffusion model:', pick)
d = hf_hub_download('leejet/FLUX.2-klein-4B-GGUF', pick, local_dir='models')
cf = list_repo_files('Comfy-Org/flux2-klein-4B')
print(cf)
vae_file = [f for f in cf if 'vae' in f.lower() and f.endswith('.safetensors')][0]
print('vae:', vae_file)
v = hf_hub_download('Comfy-Org/flux2-klein-4B', vae_file, local_dir='models')
qf = list_repo_files('unsloth/Qwen3-4B-GGUF')
qpick = [f for f in qf if f.endswith('Q4_K_M.gguf')][0]
print('llm:', qpick)
l = hf_hub_download('unsloth/Qwen3-4B-GGUF', qpick, local_dir='models')
for name, p in [('diffusion', d), ('llm', l), ('vae', v)]:
    open('models/%s_path.txt' % name, 'w').write(os.path.abspath(p))
print('done')
