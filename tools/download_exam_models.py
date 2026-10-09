"""Download ONNX CPU models only; never execute inference or benchmark."""
import json
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parents[1]
repos = {'nli': 'MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli',
         'embedding': 'intfloat/multilingual-e5-small'}
manifest = {}
for name, repo in repos.items():
    target = root / 'models' / 'exam' / name
    snapshot_download(repo, local_dir=target, allow_patterns=[
        'onnx/model.onnx', 'onnx/config.json', 'onnx/tokenizer.json',
        'onnx/tokenizer_config.json', 'onnx/special_tokens_map.json', 'LICENSE*', 'README.md'])
    for filename in ('model.onnx', 'config.json', 'tokenizer.json'):
        required = target / 'onnx' / filename
        if not required.is_file() or not required.stat().st_size:
            raise RuntimeError(f'模型下載不完整：{name}/{filename}')
    manifest[name] = {'repository': repo, 'path': str(target), 'device': 'CPU'}
    print('Downloaded:', name, flush=True)
(root / 'models' / 'exam' / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
