"""Director-specific journal, sharing AUTOPILOT jobs, checkpoints and OS worker lock."""
import hashlib
import json
import time
from uuid import uuid4
from app.models.autopilot import ChannelProfile
from app.models.autopilot_editorial import EditorialSnapshot
from app.models.historical_director import Request
from app.services.historical_director.library import SKILL_ID


class DirectorPaused(Exception):
    pass


class DirectorCancelled(Exception):
    pass


SCHEMA='''
CREATE TABLE IF NOT EXISTS director_profiles (
    channel_id TEXT PRIMARY KEY REFERENCES channels(channel_id), options TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS director_batches (
    batch_id TEXT PRIMARY KEY, reference_id TEXT NOT NULL UNIQUE,
    request TEXT NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL,
    analysis TEXT, error TEXT, pause_requested INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS director_items (
    task_id TEXT PRIMARY KEY REFERENCES editorial_jobs(task_id),
    batch_id TEXT NOT NULL REFERENCES director_batches(batch_id),
    role TEXT NOT NULL, angle_id TEXT NOT NULL, angle_version INTEGER NOT NULL,
    position INTEGER NOT NULL, context TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
    UNIQUE(batch_id,angle_id,angle_version)
);
'''


class DirectorRepositoryMixin:
    def director_profile(self,channel_id):
        with self.connect() as db:
            row=db.execute('SELECT options FROM director_profiles WHERE channel_id=?',(channel_id,)).fetchone()
            return json.loads(row[0]) if row else {}

    def save_director_profile(self,channel_id,options):
        # Same request contract validates defaults; reference-specific data are not channel defaults.
        request=Request.model_validate({'title':'Channel defaults',**options})
        values=request.model_dump(exclude={'title','reference_script','thumbnails'})
        with self.connect() as db:
            db.execute('INSERT INTO director_profiles VALUES(?,?) ON CONFLICT(channel_id) DO UPDATE SET options=excluded.options',
                       (channel_id,json.dumps(values,ensure_ascii=False)))

    def create_director_batch(self,request,snapshot,*,new_version=False):
        request=Request.model_validate(request)
        snapshot=EditorialSnapshot.model_validate(snapshot)
        if SKILL_ID not in [s.skill_id for s in snapshot.skills]:
            raise ValueError('Selecione Historical Documentary Director nas Skills salvas do canal')
        if not snapshot.channel.auto_editorial:raise ValueError('Autorize pesquisa e roteiro no canal')
        from app.services.historical_director import images
        for ref in request.thumbnails:images.read(ref)
        payload=json.dumps({'request':request.model_dump(),'snapshot':snapshot.model_dump()},sort_keys=True,ensure_ascii=False)
        identity=hashlib.sha256(payload.encode()).hexdigest()
        if new_version:identity=hashlib.sha256((identity+str(uuid4())).encode()).hexdigest()
        batch_id,task_id,now=str(uuid4()),str(uuid4()),time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT batch_id FROM director_batches WHERE reference_id=?',(identity,)).fetchone()
            if row:return row[0],False
            row=db.execute('SELECT profile FROM channels WHERE channel_id=?',(snapshot.channel.channel_id,)).fetchone()
            if not row or ChannelProfile.model_validate_json(row[0])!=snapshot.channel:
                raise ValueError('O canal mudou; confira e envie novamente')
            db.execute('INSERT INTO director_batches VALUES(?,?,?,?,?,NULL,NULL,0,?,?)',
                (batch_id,identity,request.model_dump_json(),snapshot.model_dump_json(),'analyzing',now,now))
            db.execute('INSERT INTO editorial_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                (task_id,snapshot.channel.channel_id,request.title,'director-analysis:'+batch_id,snapshot.model_dump_json(),'queued',None,None,now,now))
            db.execute('INSERT INTO director_items VALUES(?,?,?,?,?,?,?,0)',
                (task_id,batch_id,'analysis','analysis',1,0,json.dumps({'batch_id':batch_id,'reference_id':identity,'request':request.model_dump()},ensure_ascii=False)))
        return batch_id,True

    def director_batches(self,limit=20):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM director_batches ORDER BY created DESC LIMIT ?',(limit,))]

    def director_batch(self,batch_id):
        with self.connect() as db:
            row=db.execute('SELECT * FROM director_batches WHERE batch_id=?',(batch_id,)).fetchone()
            return dict(row) if row else None

    def director_item(self,task_id):
        with self.connect() as db:
            row=db.execute('SELECT * FROM director_items WHERE task_id=?',(task_id,)).fetchone()
            return dict(row) if row else None

    def director_items(self,batch_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT i.*,j.title,j.state,j.error,j.result,j.created,j.updated FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE batch_id=? ORDER BY position,task_id',(batch_id,))]

    def enqueue_director_angles(self,batch_id,selected_ids):
        from app.services.historical_director.production import snapshot_for, title_for
        if not 1<=len(selected_ids)<=5 or len(set(selected_ids))!=len(selected_ids):
            raise ValueError('Selecione de 1 a 5 ângulos distintos')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            batch=db.execute('SELECT * FROM director_batches WHERE batch_id=?',(batch_id,)).fetchone()
            if not batch or not batch['analysis']:raise ValueError('Conclua a análise antes de enfileirar')
            # Whole selection is committed once: repeated clicks return the same jobs.
            prior=db.execute("SELECT task_id FROM director_items WHERE batch_id=? AND role='production' ORDER BY position",(batch_id,)).fetchall()
            if prior:return [row[0] for row in prior],False
            if batch['state'] not in {'selection','paused'}:raise ValueError('Lote não está pronto para seleção')
            request=Request.model_validate_json(batch['request'])
            frozen=EditorialSnapshot.model_validate_json(batch['snapshot'])
            result=json.loads(batch['analysis'])
            angles={a['angle_id']:a for a in result['analysis']['alternatives']}
            if not request.angle_enabled:angles={'original':result['original_angle']}
            if any(a not in angles or not angles[a].get('eligible',False) for a in selected_ids):
                raise ValueError('Um ângulo selecionado não é elegível segundo as fontes e a revisão')
            if request.angle_enabled and request.selection_mode=='automatic':
                expected=result['recommended_ids'][:request.automatic_top_n]
                if selected_ids!=expected:raise ValueError('Seleção automática deve respeitar o ranking revisado')
            ids=[];now=time.time()
            for position,angle_id in enumerate(selected_ids,1):
                angle=angles[angle_id]
                snapshot=snapshot_for(frozen,angle,request)
                title=request.title if not request.angle_enabled else title_for(angle,frozen.channel.language)
                task_id=str(uuid4());ids.append(task_id)
                context={'batch_id':batch_id,'reference_id':batch['reference_id'],'angle_version':1,'angle':angle,
                         'request':request.model_dump(),'visual_report':result['visual_report']}
                db.execute('INSERT INTO editorial_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (task_id,frozen.channel.channel_id,title,'director:'+batch_id+':'+angle_id+':1',snapshot.model_dump_json(),'queued',None,None,now,now))
                db.execute('INSERT INTO director_items VALUES(?,?,?,?,?,?,?,0)',
                    (task_id,batch_id,'production',angle_id,1,position,json.dumps(context,ensure_ascii=False)))
            db.execute("UPDATE director_batches SET state='ready',error=NULL,pause_requested=0,updated=? WHERE batch_id=?",(now,batch_id))
            return ids,True

    def prepare_director_automatic(self):
        for batch in self.director_batches(limit=1000):
            if batch['state']!='selection':continue
            request=Request.model_validate_json(batch['request'])
            if request.angle_enabled and request.selection_mode!='automatic':continue
            result=json.loads(batch['analysis'])
            ids=result['recommended_ids'][:request.automatic_top_n] if request.angle_enabled else ['original']
            if not ids:
                with self.connect() as db:
                    db.execute("UPDATE director_batches SET state='paused',error=? WHERE batch_id=?",('Nenhum ângulo elegível; revise a pesquisa antes de produzir',batch['batch_id']))
                continue
            self.enqueue_director_angles(batch['batch_id'],ids)

    def director_available(self,db,row):
        item=db.execute('SELECT * FROM director_items WHERE task_id=?',(row['task_id'],)).fetchone()
        if not item:return True
        # A paused director job retains the sequential queue until explicitly resolved.
        if db.execute("SELECT 1 FROM director_batches WHERE state='paused' LIMIT 1").fetchone():return False
        batch=db.execute('SELECT * FROM director_batches WHERE batch_id=?',(item['batch_id'],)).fetchone()
        if batch['pause_requested'] or batch['state']=='paused':return False
        if item['role']=='analysis':return batch['state']=='analyzing'
        if batch['state'] not in {'ready','running'}:return False
        policy=json.loads(batch['request'])['on_failure']
        prior=db.execute("SELECT j.state FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE i.batch_id=? AND i.role='production' AND i.position<?",(item['batch_id'],item['position'])).fetchall()
        terminal={'completed','cancelled'}|({'failed','blocked'} if policy=='skip' else set())
        return all(p[0] in terminal for p in prior)

    def check_director_control(self,task_id):
        with self.connect() as db:
            item=db.execute('SELECT * FROM director_items WHERE task_id=?',(task_id,)).fetchone()
            if not item:return
            if item['cancel_requested']:raise DirectorCancelled()
            batch=db.execute('SELECT pause_requested,state FROM director_batches WHERE batch_id=?',(item['batch_id'],)).fetchone()
            if batch[0] or batch[1]=='paused':raise DirectorPaused()

    def director_finished(self,db,task_id,state,result,error):
        item=db.execute('SELECT * FROM director_items WHERE task_id=?',(task_id,)).fetchone()
        if not item:return
        batch=db.execute('SELECT * FROM director_batches WHERE batch_id=?',(item['batch_id'],)).fetchone()
        request=Request.model_validate_json(batch['request'])
        now=time.time()
        if item['role']=='analysis' and state=='completed':
            db.execute("UPDATE director_batches SET state=?,analysis=?,error=NULL,updated=? WHERE batch_id=?",
                       ('paused' if batch['pause_requested'] else 'selection',json.dumps(result,ensure_ascii=False),now,item['batch_id']))
            return
        if state in {'blocked','failed','paused'} and (request.on_failure=='pause_queue' or item['role']=='analysis' or state=='paused'):
            db.execute("UPDATE director_batches SET state='paused',error=?,updated=? WHERE batch_id=?",(error,now,item['batch_id']))
            return
        remaining=db.execute("SELECT count(*) FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE batch_id=? AND role='production' AND j.state NOT IN ('completed','cancelled','failed','blocked')",(item['batch_id'],)).fetchone()[0]
        db.execute('UPDATE director_batches SET state=?,updated=? WHERE batch_id=?',(('paused' if batch['pause_requested'] or batch['state']=='paused' else 'running') if remaining else 'completed',now,item['batch_id']))

    def pause_director(self,batch_id):
        with self.connect() as db:
            db.execute("UPDATE director_batches SET pause_requested=1,state=CASE WHEN state='completed' THEN state ELSE 'paused' END,updated=? WHERE batch_id=?",(time.time(),batch_id))

    def resume_director(self,batch_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            batch=db.execute('SELECT * FROM director_batches WHERE batch_id=?',(batch_id,)).fetchone()
            if not batch or batch['state']=='completed':return False
            failed=db.execute("SELECT count(*) FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE batch_id=? AND j.state IN ('failed','blocked')",(batch_id,)).fetchone()[0]
            if failed and json.loads(batch['request'])['on_failure']=='pause_queue':
                raise ValueError('Revise a falha e autorize a repetição ou cancele o item antes de retomar')
            count=db.execute("SELECT count(*) FROM director_items WHERE batch_id=? AND role='production'",(batch_id,)).fetchone()[0]
            state='ready' if count else ('selection' if batch['analysis'] else 'analyzing')
            db.execute("UPDATE editorial_jobs SET state='queued' WHERE state='paused' AND task_id IN (SELECT task_id FROM director_items WHERE batch_id=?)",(batch_id,))
            db.execute('UPDATE director_batches SET state=?,pause_requested=0,error=NULL,updated=? WHERE batch_id=?',(state,time.time(),batch_id))
            return True

    def cancel_director_item(self,task_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            item=db.execute('SELECT * FROM director_items WHERE task_id=?',(task_id,)).fetchone()
            if not item:return False
            row=db.execute('SELECT state FROM editorial_jobs WHERE task_id=?',(task_id,)).fetchone()
            if row[0] in {'completed','cancelled'}:return False
            db.execute('UPDATE director_items SET cancel_requested=1 WHERE task_id=?',(task_id,))
            if row[0]!='running':
                db.execute("UPDATE editorial_jobs SET state='cancelled',updated=? WHERE task_id=?",(time.time(),task_id))
                self.director_finished(db,task_id,'cancelled',None,None)
            return True

    def reorder_director(self,batch_id,task_ids):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pending=db.execute("SELECT i.task_id,i.position FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE batch_id=? AND role='production' AND j.state='queued' ORDER BY i.position",(batch_id,)).fetchall()
            if len(task_ids)!=len(pending) or set(task_ids)!={p[0] for p in pending}:raise ValueError('Reordene apenas todos os itens pendentes')
            active=db.execute("SELECT max(i.position) FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE batch_id=? AND role='production' AND j.state NOT IN ('queued','cancelled')",(batch_id,)).fetchone()[0] or 0
            if pending and min(p['position'] for p in pending)<=active:raise ValueError('Não é possível mover itens anteriores ao item já iniciado')
            for pos,task_id in zip(sorted(p['position'] for p in pending),task_ids):
                db.execute('UPDATE director_items SET position=? WHERE task_id=?',(pos,task_id))

    def director_previous(self,batch_id,task_id):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT result FROM editorial_jobs j JOIN director_items i USING(task_id) WHERE batch_id=? AND role='production' AND task_id!=? AND j.state='completed' ORDER BY position",(batch_id,task_id))]

    def replace_director_references(self,task_id,refs,enabled):
        from app.models.historical_director import ImageRef
        refs=[ImageRef.model_validate(ref) for ref in refs]
        if len(refs)>3:raise ValueError('Envie no máximo 3 thumbnails')
        # Existing remote analysis is never overwritten. New references are analyzed by their own checkpoint.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            item=db.execute('SELECT i.*,j.state FROM director_items i JOIN editorial_jobs j USING(task_id) WHERE task_id=?',(task_id,)).fetchone()
            if not item or item['role']!='production' or item['state']!='queued':raise ValueError('Só é possível substituir referências de um item pendente')
            if db.execute('SELECT count(*) FROM editorial_stages WHERE task_id=?',(task_id,)).fetchone()[0]:raise ValueError('O item já iniciou; suas referências estão congeladas')
            context=json.loads(item['context']);request=Request.model_validate(context['request'])
            request.thumbnails=refs;request.thumbnail_reference_enabled=enabled
            request=Request.model_validate(request.model_dump())
            context['request']=request.model_dump();context['visual_override']=True
            version=item['angle_version']+1;context['angle_version']=version
            db.execute('UPDATE director_items SET angle_version=?,context=? WHERE task_id=?',(version,json.dumps(context,ensure_ascii=False),task_id))
            db.execute('UPDATE editorial_jobs SET identity_hash=? WHERE task_id=?',('director:'+item['batch_id']+':'+item['angle_id']+':'+str(version),task_id))

    def cancel_director_batch(self,batch_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE director_items SET cancel_requested=1 WHERE batch_id=? AND task_id IN (SELECT task_id FROM editorial_jobs WHERE state!='completed')",(batch_id,))
            db.execute("UPDATE editorial_jobs SET state='cancelled',updated=? WHERE state NOT IN ('running','completed','cancelled') AND task_id IN (SELECT task_id FROM director_items WHERE batch_id=?)",(time.time(),batch_id))
            db.execute("UPDATE director_batches SET state='completed',pause_requested=0,error='Lote encerrado; resultados concluídos preservados',updated=? WHERE batch_id=?",(time.time(),batch_id))
