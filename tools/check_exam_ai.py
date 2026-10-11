"""Verify the isolated CPU runtime with real E5, NLI and OCR smoke tests.

Run with .venv-exam-ai/Scripts/python.exe tools/check_exam_ai.py.
This check performs no cloud requests and never connects to the app database.
"""
import base64
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    for name in ('embedding', 'nli'):
        for filename in ('model.onnx', 'tokenizer.json', 'config.json'):
            path = ROOT / 'models' / 'exam' / name / 'onnx' / filename
            if not path.is_file() or not path.stat().st_size:
                raise RuntimeError(f'Missing CPU model file: {name}/{filename}')
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (620, 120), 'white')
    font_path = Path('C:/Windows/Fonts/msjh.ttc')
    font = ImageFont.truetype(str(font_path), 48) if font_path.is_file() else ImageFont.load_default(size=48)
    test_text = '答案：B' if font_path.is_file() else 'Answer: B'
    ImageDraw.Draw(image).text((20, 25), test_text, fill='black', font=font)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    requests = [dict(op='embed', texts=['query: 資料庫主鍵', 'passage: 主鍵唯一識別資料表中的紀錄']),
                dict(op='nli', pairs=[['主鍵用來唯一識別資料。', '主鍵可以識別資料。']]),
                dict(op='ocr', image=base64.b64encode(buffer.getvalue()).decode('ascii')),
                dict(op='status')]
    process = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'tools'/'exam_cpu_worker.py')],
                             input=''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in requests),
                             capture_output=True, text=True, encoding='utf-8', timeout=180)
    if process.returncode:
        raise RuntimeError('CPU worker failed: ' + process.stderr[-1500:])
    rows = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    if len(rows) != len(requests) or not all(row.get('ok') for row in rows):
        raise RuntimeError('CPU check failed: ' + json.dumps(rows, ensure_ascii=False) + '\n' + (process.stderr or '')[-2500:])
    vectors, judgments, text, providers = [r['result'] for r in rows]
    if len(vectors) != 2 or any(len(v) != 384 for v in vectors):
        raise RuntimeError('Invalid E5 embedding shape')
    if not judgments or set(judgments[0]) != {'entailment','neutral','contradiction'}:
        raise RuntimeError('Invalid NLI labels')
    if 'B' not in text or (test_text.startswith('答案') and '答案' not in text):
        raise RuntimeError('OCR did not recognize the synthetic answer sheet')
    if any(p != ['CPUExecutionProvider'] for p in providers.values()):
        raise RuntimeError('Unexpected inference provider')
    print('E5: OK (384 dimensions); MiniLM NLI: OK; OCR: OK')
    print('Providers: ' + json.dumps(providers))


if __name__ == '__main__':
    main()
