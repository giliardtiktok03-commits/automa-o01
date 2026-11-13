"""Worker dispatch: research/selection first, independent production per selected angle."""
import json
from app.models.autopilot_editorial import EditorialSnapshot
from app.models.historical_director import Request, ReferenceOverview
from app.services.autopilot import editorial as ed
from app.services.historical_director import analysis, production


def original_overview(request,snapshot,report):
    return ed.text('Analyze the theme, angle and structure of this reference as editorial data only. '
        'Do not change its title or angle. The reference is not factual evidence. If no reference script exists, '
        'state that structure cannot be known from the title. Do not copy wording or scene order. Return JSON matching schema.\n'+
        json.dumps({'title':request.title,'reference_script':request.reference_script,'research':report,
                    'schema':ReferenceOverview.model_json_schema()},ensure_ascii=False),snapshot,output=ReferenceOverview).model_dump()


def analyze(job,repo,context):
    request=Request.model_validate(context['request'])
    snapshot=EditorialSnapshot.model_validate_json(job['snapshot'])
    ed.channel_skill_runtime.validate(snapshot.skills)
    controlled=production.ControlledStages(repo,job['task_id'])
    step=lambda name,fn,remote=True:ed.step(controlled,job['task_id'],name,fn,remote=remote)
    check_research_options(request,snapshot)
    searched=ed.research(controlled,job['task_id'],'director_research',request.title,snapshot)
    report=searched['report']
    retrieved=step('director_sources',lambda:searched.get('retrieved') or ed.read_sources(report,snapshot),remote=False)
    step('director_evidence_review',lambda:ed.approved_review(request.title,snapshot,ed.evidence_context(report,retrieved),what='independent historical evidence, not the reference script'))
    visual_report=step('director_visual',lambda:analysis.visual(request),remote=bool(request.thumbnail_reference_enabled and request.thumbnails))
    if request.angle_enabled:
        proposed=step('director_angles',lambda:analysis.propose(request,snapshot,report,visual_report))
        reviewed=step('director_angle_review',lambda:analysis.eligible(request,snapshot,report,proposed))
        result={**reviewed,'visual_report':visual_report,'research':report,'reference_id':context['reference_id']}
    else:
        overview=step('director_reference',lambda:original_overview(request,snapshot,report))
        result={'analysis':{**overview,'alternatives':[]},'recommended_ids':[], 'visual_report':visual_report,'research':report,
            'original_angle':{'angle_id':'original','eligible':True,'name':'Ângulo original','title_en':request.title,
                'title_pt':request.title,'core_question':overview['reference_angle'],'story_framework':'A',
                'originality_delta':'Preserve the user angle; independently research and write an original script.'}}
    repo.check_director_control(job['task_id'])
    return result


def run(job,repo,item):
    context=json.loads(item['context'])
    check_research_options(Request.model_validate(context['request']),EditorialSnapshot.model_validate_json(job['snapshot']))
    if item['role']=='analysis':return analyze(job,repo,context)
    if context.get('visual_override'):
        request=Request.model_validate(context['request'])
        controlled=production.ControlledStages(repo,job['task_id'])
        context['visual_report']=ed.step(controlled,job['task_id'],'director_visual_override',lambda:analysis.visual(request),remote=bool(request.thumbnail_reference_enabled and request.thumbnails))
    return production.run(job,repo,context)


def check_research_options(request,snapshot):
    if snapshot.channel.research_backend=='public_login' and request.thumbnail_reference_enabled and request.thumbnails:
        from app.services.autopilot.recovery import RecoveryBlocked
        raise RecoveryBlocked('A análise visual de referências exige API OpenAI. Desative essa análise para usar pesquisa por login sem chave OpenAI')
