"""Conservative, scale-independent ownership of PDF visual regions.

Coordinates are only supporting evidence: explicit reading scopes come first.
Uncertain/cross-column regions retain candidates rather than acquiring an owner.
"""
from statistics import median


def question_crops(anchors,questions,numbers,page_width,page_height,image_regions=()):
    """Crop selected question columns while retaining their full shared text.

    If boundaries cannot be supported, return the whole page for review. Crop
    sizes follow label font bands, not a question-specific pixel threshold.
    """
    selected=[q for q in questions if q['number'] in numbers]
    if not selected: return [(0,0,page_width,page_height)]
    if any(region.get('status')=='unresolved' and set(region.get('candidates',[])) & set(numbers) for region in image_regions):
        return [(0,0,page_width,page_height)]
    height=median(q['bbox'][3]-q['bbox'][1] for q in questions)
    starts=[]
    for x in sorted(q['bbox'][0] for q in questions):
        if not starts or x-starts[-1]>max(page_width*.12,height*3): starts.append(x)
    def column(x): return min(range(len(starts)),key=lambda i:abs(x-starts[i]))
    edges=[0]+[x-height for x in starts[1:]]+[page_width]
    crops=[]
    for col in sorted({column(q['bbox'][0]) for q in selected}):
        own=[q for q in selected if column(q['bbox'][0])==col]
        top=min(q['bbox'][1] for q in own)-height*.15
        bottom=max(q['bbox'][3] for q in own)
        following=[q['bbox'][1] for q in questions if column(q['bbox'][0])==col and q['bbox'][1]>bottom]
        bottom=min(following)-height*.15 if following else page_height
        for anchor in anchors:
            if column(anchor['bbox'][0])==col and any(anchor['question_from']<=q['number']<=anchor['question_to'] for q in own):
                top=min(top,anchor['bbox'][1]-height*.15)
        for region in image_regions:
            limits=region.get('range')
            if region.get('status')=='assigned' and limits and any(limits[0]<=q['number']<=limits[1] for q in own):
                top=min(top,region['bbox'][1])
                bottom=max(bottom,region['bbox'][3])
        crops.append((edges[col],max(0,top),edges[col+1],min(page_height,bottom)))
    return crops


def visual_region(anchors, questions, bbox, page_width, carried_range=None):
    if not questions:
        return dict(range=None, candidates=[], status='unresolved', reason='no_question_regions')
    # Infer column starts from question labels, not page midpoint / image center.
    starts=sorted(q['bbox'][0] for q in questions)
    heights=[q['bbox'][3]-q['bbox'][1] for q in questions]
    line_height=median(heights)
    clusters=[]
    for x in starts:
        if not clusters or x-median(clusters[-1])>max(page_width*.12,line_height*3):
            clusters.append([x])
        else: clusters[-1].append(x)
    origins=[median(c) for c in clusters]
    def column(x): return min(range(len(origins)),key=lambda i:abs(x-origins[i]))
    # A column starts at its labels; the gutter precedes the next label.
    edges=[0]+[x-line_height for x in origins[1:]]+[page_width]
    width=max(bbox[2]-bbox[0],1e-9)
    overlaps=[max(0,min(bbox[2],edges[i+1])-max(bbox[0],edges[i]))/width for i in range(len(origins))]
    col=max(range(len(origins)),key=overlaps.__getitem__)
    local=sorted((q for q in questions if column(q['bbox'][0])==col),key=lambda q:q['bbox'][1])
    candidates=[q['number'] for q in local if q['bbox'][1]<=bbox[3] and q['bbox'][3]>=bbox[1]]
    if overlaps[col]<.9:
        return dict(range=None,candidates=candidates,status='unresolved',reason='cross_column_region')
    # First-line overlap beats preceding top coordinates. This follows the
    # actual font band at every scale, without a fixed pixel correction.
    same_line=[q for q in local if q['bbox'][1]<=bbox[1]<=q['bbox'][3]]
    preceding=[q for q in local if q['bbox'][1]<=bbox[1]]
    owner=same_line[-1] if same_line else (preceding[-1] if preceding else None)
    # The image may begin slightly above its label but intersects that label's
    # band. Accept only when it doesn't also cover a following question label.
    next_label=next((q for q in local if candidates and q['number']==candidates[0]),None)
    if next_label and (owner is None or next_label['number']!=owner['number']):
        # Only the immediate label band can supersede a preceding region.
        # A tall image crossing a later label is ambiguous, not that later q.
        if next_label['bbox'][1]-bbox[1]<=next_label['bbox'][3]-next_label['bbox'][1]:
            owner=next_label
    if owner is None:
        return dict(range=None,candidates=[],status='unresolved',reason='before_question_region')
    active=[a for a in anchors if column(a['bbox'][0])==col and a['bbox'][1]<=bbox[1]]
    active.sort(key=lambda a:a['bbox'][1])
    group=active[-1] if active else None
    limits=(group['question_from'],group['question_to']) if group else carried_range
    if limits and limits[0]<=owner['number']<=limits[1]:
        if all(limits[0]<=n<=limits[1] for n in candidates):
            return dict(range=limits,candidates=candidates,status='assigned',reason='explicit_reading_scope')
    if any(n!=owner['number'] for n in candidates):
        return dict(range=None,candidates=sorted(set(candidates+[owner['number']])),status='unresolved',reason='multiple_question_regions')
    return dict(range=(owner['number'],owner['number']),candidates=[owner['number']],status='assigned',reason='question_region_and_line_band')
