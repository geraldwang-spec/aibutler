"""Train CPU heads from a manually curated JSONL file; never auto-label training data."""
import argparse
import json
from collections import Counter
from pathlib import Path
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

parser=argparse.ArgumentParser()
parser.add_argument('dataset',help='JSONL: content,q_type,concept_name,skill,cognitive_level,subject_id,human_verified=true')
args=parser.parse_args()
rows=[json.loads(line) for line in Path(args.dataset).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
rows=[r for r in rows if r.get('human_verified') is True and r.get('content')]
root=Path(__file__).resolve().parents[1]
manifest={}
# A separate subject-specific concept model avoids merging unrelated courses.
groups={'global':rows}
for row in rows:
    if row.get('subject_id') is not None:
        groups.setdefault('subject_'+str(int(row['subject_id'])),[]).append(row)
for scope, data in groups.items():
    target=root/'models'/'exam'/'trained'/scope
    target.mkdir(parents=True,exist_ok=True)
    manifest[scope]={}
    for field in ('q_type','concept_name','skill','cognitive_level'):
        if scope=='global' and field in ('concept_name','skill'):
            continue
        selected=[r for r in data if r.get(field)]
        counts=Counter(r[field] for r in selected)
        if len(counts)<2 or min(counts.values(),default=0)<20:
            manifest[scope][field]={'status':'insufficient_data','counts':dict(counts),'minimum_per_label':20}
            print('Not trained:',scope,field,'requires at least 20 verified examples per label')
            continue
        model=make_pipeline(TfidfVectorizer(analyzer='char',ngram_range=(2,5),max_features=30000),
                            LogisticRegression(max_iter=1000,class_weight='balanced'))
        model.fit([r['content'] for r in selected],[r[field] for r in selected])
        joblib.dump(model,target/(field+'.joblib'))
        manifest[scope][field]={'status':'trained_unvalidated','counts':dict(counts)}
        print('Trained, not validated:',scope,field)
(root/'models'/'exam'/'trained'/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
