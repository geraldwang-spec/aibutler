"""Fetch only the explicitly curated demonstration photos; no database access.

Run from the repository: python tools/download_exercise_media.py
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from body.exercise_media import EXERCISE_MEDIA, MEDIA_ROOT


def main():
    base = 'https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/'
    with urllib.request.urlopen(base + 'dist/exercises.json', timeout=30) as response:
        catalog = {item['id']: item for item in json.load(response)}
    jobs = []
    for slug in sorted(set(EXERCISE_MEDIA.values())):
        item = catalog[slug]
        for index in range(2):
            image = item['images'][index]
            if image != f'{slug}/{index}.jpg':
                raise ValueError('Unexpected upstream image path: ' + slug)
            jobs.append((base + 'exercises/' + image, MEDIA_ROOT / image))

    def download(job):
        url, path = job
        if path.is_file():
            return
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read(5_000_001)
        if not content.startswith(b'\xff\xd8\xff') or len(content) > 5_000_000:
            raise ValueError('Invalid JPEG: ' + path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(download, jobs))
    print(f'Validated {len(jobs)} photos for {len(EXERCISE_MEDIA)} exercise names.')


if __name__ == '__main__':
    main()
