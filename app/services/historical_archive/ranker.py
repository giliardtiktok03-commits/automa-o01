import re

STOP={'the','and','for','with','this','that','from','uma','para','com','que','dos','das','em','no','na','de','do','da','of','in','on','at','a','an','as','is','os','as','scene','close','up','archival','photograph','historical','photo','today','present','day'}


def tokens(text):
    return {v for v in re.findall(r'[\w-]+',str(text).lower()) if len(v)>2 and v not in STOP}


def rank(candidate, query, rights_status):
    words=tokens(' '.join(query['queries']))
    title=tokens(candidate.title+' '+candidate.description)
    subject={w for w in words if not w.isdigit()}
    overlap=len(subject & title)/max(1,len(subject))
    dates=set(query['dates'])
    found=set(re.findall(r'\b(?:1[0-9]{3}|20[0-9]{2})\b',candidate.date_created+' '+candidate.title))
    temporal=1 if dates and dates & found else 0 if dates and found else .4
    entities=tokens(query.get('location',''))
    entity=min(1,len(entities & title)/max(1,len(entities))) if entities else overlap
    width=candidate.metadata.get('width',0) or 0
    quality=1 if isinstance(width,(int,float)) and width>=1000 else .5 if candidate.download_url else 0
    rights=1 if rights_status=='rights_cleared' else 0
    score=round(30*overlap+25*temporal+20*entity+15*quality+10*rights,2)
    # Explicit conflicting dates/equipment must not be hidden by generic overlap.
    ids=set(re.findall(r'\b[a-z]+-\d+\b',' '.join(query['queries']).lower()))
    candidate_ids=set(re.findall(r'\b[a-z]+-\d+\b',(candidate.title+' '+candidate.description).lower()))
    mismatch=(bool(dates and found and not dates & found) or bool(ids and candidate_ids and not ids & candidate_ids))
    if mismatch:score=min(score,15)
    return score, {'event':round(overlap,3),'temporal':temporal,'entities':round(entity,3),
                  'quality':quality,'rights_metadata':rights,'conflicting_context':mismatch}
