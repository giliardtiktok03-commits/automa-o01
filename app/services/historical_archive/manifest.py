import json
from datetime import datetime,timezone
from app.utils.atomic_files import write_bytes_atomic


def now():return datetime.now(timezone.utc).isoformat()


def read(folder):
    path=folder/'manifest.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version':1,'scenes':{},'providers':{},'downloads':{}}


def save(folder,data):
    folder.mkdir(parents=True,exist_ok=True)
    write_bytes_atomic(folder/'manifest.json',json.dumps(data,ensure_ascii=False,indent=2).encode())
    credits(folder,data)
    write_bytes_atomic(folder/'search_log.json',json.dumps({'providers':data['providers'],'scenes':{
        key:{'queries':s.get('query',{}),'status':s.get('status'),'searched_at':s.get('searched_at')} for key,s in data['scenes'].items()}},ensure_ascii=False,indent=2).encode())


def credits(folder,data):
    lines=['# Sources and credits — only materials used in the video','']
    used=[]
    for scene_id,scene in data['scenes'].items():
        for item in scene.get('candidates',[]):
            if not item.get('used'):continue
            used.append({'scene_id':scene_id,**item})
            c=item['candidate']
            lines.extend([f"## Scene {scene_id}: {c['title']}",
                f"- Institution: {c['institution']}",f"- Creator/date: {c['creator']} / {c['date_created']}",
                f"- Record: {c['record_id']}",f"- Source: {c['source_url']}",f"- File URL: {c['download_url']}",
                f"- Rights: {c['rights_statement']}",f"- License: {c['license_url']}",f"- Attribution: {c['attribution']}",
                f"- Decision: {item['rights_status']}; {item.get('decision',{})}",f"- Consulted: {scene.get('searched_at','')}",
                f"- Authenticity: {c['metadata'].get('authenticity','unverified')}",''])
    write_bytes_atomic(folder/'sources_and_credits.md','\n'.join(lines).encode())
    write_bytes_atomic(folder/'sources_and_credits.json',json.dumps(used,ensure_ascii=False,indent=2).encode())
