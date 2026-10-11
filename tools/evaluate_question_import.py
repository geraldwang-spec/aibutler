"""Opt-in public-corpus/layout smoke tests; never opens production DB.

python tools/evaluate_question_import.py [--live]
Live mode records physical API attempts and token usage without imposing quotas.
Source PDFs are cached in tmp/pdfs/import-corpus; report contains no API keys.
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from personal_ai.parsers import parse_file,exam_sections,pdf_question_anchors,pdf_reading_anchors
from personal_ai.layout_regions import visual_region
from personal_ai.question_importer import extract_by_rules,_question_start
from personal_ai.import_routing import plan_repairs,extract_unit_with_vision

CORPUS={
    'chinese':('https://pic.tcte.edu.tw/SELF/114Self/114Self_6-00-C.pdf',50),
    'english':('https://pic.tcte.edu.tw/SELF/114Self/114Self_6-00-E.pdf',50),
    'math':('https://pic.tcte.edu.tw/SELF/114Self/114Self_6-08-1.pdf',20),
}


def main():
    import pymupdf
    args=argparse.ArgumentParser()
    args.add_argument('--live',action='store_true')
    args.add_argument('--only',default='',help='Comma-separated live case names; offline corpus still evaluated')
    args.add_argument('--report-name',default='report.json')
    args=args.parse_args()
    if Path(args.report_name).name!=args.report_name: raise ValueError('Report must be a filename')
    cache=ROOT/'tmp/pdfs/import-corpus'; cache.mkdir(parents=True,exist_ok=True)
    out=ROOT/'output/import-evaluation'; out.mkdir(parents=True,exist_ok=True)
    report=dict(corpus=[],live=[],calls=0,input_tokens=0,output_tokens=0,
                limitations='Structural smoke tests, not a calibrated accuracy estimate; no production data modified.')
    cases=[]
    for name,(url,expected) in CORPUS.items():
        path=cache/(name+'.pdf')
        if not path.exists():
            with urllib.request.urlopen(url,timeout=30) as response: path.write_bytes(response.read())
        sections=exam_sections(parse_file(path))
        items=extract_by_rules(sections,name,True)
        try:
            units,numbers=plan_repairs(sections,items)
            error=None
        except ValueError as exc:
            units=[]; numbers={_question_start(line) for section in sections for line in section['text'].splitlines()}-{None}; error=str(exc)
        report['corpus'].append(dict(name=name,url=url,expected=expected,parsed=len(items),
                                    source_numbers=len(numbers),repair_units=[u['numbers'] for u in units],error=error))
        first=next((s for s in sections if _question_start(s['text'].splitlines()[0]) is not None),sections[0])
        page_no=int(first['locator'].split(':')[1])-1
        with pymupdf.open(path) as doc:
            doc[page_no].get_pixmap(matrix=pymupdf.Matrix(1,1)).save(cache/(name+'-page.png'))
        number=min(numbers)
        lines=first['text'].splitlines(); selected=[]; collecting=False
        for line in lines:
            q=_question_start(line)
            if q==number: collecting=True
            elif q is not None and collecting: break
            if collecting: selected.append(line)
        cases.append((name,path,dict(numbers=[number],text='\n'.join(selected),source_pages=[page_no])))
        if name=='english':
            for section in sections:
                if any(_question_start(line)==36 for line in section['text'].splitlines()):
                    cases.append(('english-reading',path,dict(numbers=[36],text=section['text'],source_pages=[int(section['locator'].split(':')[1])-1])))
                    break
        print(name,report['corpus'][-1],flush=True)
    user_pdf=Path('C:/Users/tyy801124/OneDrive/文件/115會考國文題本.pdf')
    if user_pdf.exists():
        with pymupdf.open(user_pdf) as doc:
            page=doc[0]; questions=pdf_question_anchors(page); anchors=pdf_reading_anchors(page)
            report['local_image_regions']=[dict(bbox=list(info['bbox']),**visual_region(anchors,questions,info['bbox'],page.rect.width)) for info in page.get_image_info() if info['bbox'][3]-info['bbox'][1]>=25]
            lines=page.get_text().splitlines(); selected=[]; collecting=False
            for line in lines:
                q=_question_start(line)
                if q==3: collecting=True
                elif q is not None and collecting: break
                if collecting: selected.append(line)
        for repetition in range(2): cases.insert(0,('local-chinese-repeat-'+str(repetition+1),user_pdf,dict(numbers=[3],text='\n'.join(selected),source_pages=[0])))
    if args.live:
        from dotenv import dotenv_values
        from personal_ai.llm_provider import LLMError
        config=dict(dotenv_values(ROOT/'.env'))
        def guard(*args):
            report['calls']+=1
        def usage(data,model,elapsed):
            values=data.get('usage') or {}
            report['input_tokens']+=int(values.get('prompt_tokens') or 0)
            report['output_tokens']+=int(values.get('completion_tokens') or 0)
        with patch('personal_ai.jobs.guard',side_effect=guard),patch('personal_ai.jobs.usage',side_effect=usage):
            for name,path,unit in cases:
                if args.only and name not in args.only.split(','): continue
                try:
                    rows=extract_unit_with_vision(unit,path,name,config)
                    row=rows[0]
                    result=dict(name=name,number=row['_question_no'],content=row['content'],
                                options={k:row.get('option_'+k) for k in 'ABCD'},structural_pass=True)
                    if name.startswith('local-chinese'):
                        result['no_neighbor_dictionary']='三足' not in row['content'] and '說文解字' not in row['content']
                        result['both_sources']='資料一' in row['content'] and '資料二' in row['content']
                    report['live'].append(result)
                    print(name,'completed',flush=True)
                except (LLMError,RuntimeError) as exc:
                    report['live'].append(dict(name=name,error=str(exc),structural_pass=False))
                    print(name,'failed',str(exc),flush=True)
                (out/args.report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/args.report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('physical_calls',report['calls'],'tokens',report['input_tokens'],report['output_tokens'],flush=True)


if __name__=='__main__': main()
