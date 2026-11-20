"""One numbered, self-contained workspace for direct YouTube publishing."""
from pathlib import Path
import streamlit as st
from app.services.youtube_publish.store import Store,PublishError
from app.services.youtube_publish import auth,service
from app.utils import utils


@st.fragment(run_every=3)
def connection_status(channel):
    pending=auth.status(channel)
    if pending.get('url'):st.link_button('Autorizar canal no Google',pending['url'])
    if pending.get('state') in {'starting','waiting'}:
        st.info('Aguardando autorização. Abra o link no navegador deste mesmo computador. Prazo: 5 minutos.')
    if pending.get('state')=='failed':st.warning(pending['error'])
    cfg=Store().connection(channel)
    if cfg.get('connected'):st.success('Canal conectado: '+cfg['youtube_channel_name']+' · '+cfg['youtube_channel_id'])
    if st.button('Atualizar conexão',key='yt_connection_refresh'):st.rerun(scope='app')


@st.fragment(run_every=5)
def history(channel):
    store=Store();jobs=store.jobs(channel)
    st.markdown('**4 · Histórico e retomada**')
    st.caption('Se o MPT fechar durante um envio, volte aqui e retome a postagem salva. Uma sessão iniciada sem confirmação exige revisão no YouTube Studio.')
    for job in jobs:
        with st.expander(job['metadata']['snippet']['title']+' · '+job['state']):
            st.caption('Projeto: '+Path(job['video']).parent.name)
            if job.get('origin')=='director_package':st.caption('Pacote da Skill · '+job.get('angle_id','')+' · metadados e thumbnail próprios deste vídeo')
            if job.get('url'):st.link_button('Abrir vídeo no YouTube',job['url'])
            if job.get('error'):st.warning(job['error'])
            if job.get('video_bytes') and not job.get('video_id'):st.progress(min(1.,job.get('offset',0)/job['video_bytes']))
            st.download_button('Baixar registro da postagem',data=__import__('json').dumps(job,ensure_ascii=False,indent=2),
                file_name='youtube-publication.json',key='yt_record_'+job['id'])
            reviewed=not job.get('review_required') or job.get('review_approved',False)
            if job['state']!='completed' and job.get('origin')=='director_package':
                st.json(job['metadata'])
                thumbnail=Path(job['video']).parent/'youtube-thumbnail.jpg'
                if thumbnail.is_file():st.image(str(thumbnail),caption='Thumbnail deste vídeo',width=320)
            if job['state']!='completed' and job.get('review_required'):
                reviewed=st.checkbox('Revisei este vídeo, a thumbnail, os direitos e os créditos do pacote',value=job.get('review_approved',False),key='yt_review_'+job['id'])
            if job['state']!='completed' and st.button('Enviar / retomar postagem',key='yt_resume_'+job['id'],disabled=not reviewed):
                try:service.submit(job['id'],store,reviewed=reviewed);st.info('Postagem encaminhada à fila. O resultado será atualizado aqui.')
                except PublishError as exc:st.warning(str(exc))
    st.button('Atualizar postagens',key='yt_history_refresh')


def render(params,heading=None):
    with st.container(key='youtube_publish_workspace'):
        if heading:heading(5,'Postagem automática youtube','#d93025')
        else:st.subheader('05 · Postagem automática youtube')
        with st.expander('YouTube direto · conexão, metadados e postagens',expanded=False):
            st.caption('API oficial do YouTube, sem assinatura do Upload-Post. Cotas e restrições do Google se aplicam. O envio fica desligado até você configurar e ativar.')
            from app.services.autopilot.repository import Repository
            channels=Repository().channels()
            if not channels:
                st.info('Cadastre primeiro um canal no AUTOPILOT. A autorização Google será vinculada a esse cadastro.')
                return
            by_id={c['channel_id']:c for c in channels}
            channel=st.selectbox('Canal do MPT para postagem',list(by_id),format_func=lambda k:by_id[k]['name']+' · '+k,key='yt_channel')
            store=Store();cfg=store.connection(channel)
            with st.container(key='youtube_configuration_grid'):
                columns=st.columns(4)
            names=['connection','metadata','video','history']
            panels=[col.container(border=True,key='yt_'+name+'_panel') for col,name in zip(columns,names)]
            with panels[0]:
                st.markdown('**1 · Conectar o canal**')
                st.markdown('[Abrir Google Cloud Console](https://console.cloud.google.com/apis/library/youtube.googleapis.com) · [Configurar OAuth](https://console.cloud.google.com/auth/clients)')
                st.caption('Ative YouTube Data API v3, configure a tela de consentimento e crie um cliente OAuth do tipo Aplicativo para computador. Em modo de teste, adicione sua conta como usuário de teste. Baixe o JSON e carregue abaixo. Não é uma chave de API comum.')
                st.caption('A autorização Google permite gerenciar vídeos do canal, pois a API exige essa permissão para mudar a privacidade após o upload. O módulo não oferece exclusão de vídeos.')
                st.caption('Projetos não auditados podem ter uploads restritos a privados. Em OAuth externo no modo de teste, a autorização pode expirar após 7 dias. Este módulo começa com privacidade privada.')
                client=st.file_uploader('JSON OAuth do Google — aplicativo para computador',type=['json'],key='yt_oauth_file')
                if st.button('Conectar canal ao Google',key='yt_connect',disabled=client is None):
                    try:auth.connect(channel,client.getvalue(),store);st.info('Preparando autorização Google. Aguarde o link abaixo.')
                    except PublishError as exc:st.warning(str(exc))
                connection_status(channel)
                if cfg.get('connected') and st.button('Desconectar deste MPT',key='yt_disconnect'):
                    try:auth.disconnect(channel,store);st.rerun()
                    except PublishError as exc:st.warning(str(exc))
                st.caption('A desconexão remove o token local. Para revogar a permissão no Google, use Segurança → Conexões com terceiros na sua conta.')
            with panels[1]:
                st.markdown('**2 · Dados da postagem**')
                suffix='_'+channel
                title=st.text_input('Título no YouTube — envio de vídeo salvo',value=params.video_subject or '',max_chars=100,key='yt_title'+suffix)
                description=st.text_area('Descrição completa, referências e hashtags',value=cfg.get('description',''),height=160,key='yt_description'+suffix)
                tags_text=st.text_input('Tags separadas por vírgula',value=', '.join(cfg.get('tags',[])),key='yt_tags'+suffix)
                tags=[s.strip() for s in tags_text.split(',') if s.strip()]
                privacy=st.selectbox('Privacidade do vídeo',['private','unlisted','public'],
                    index=['private','unlisted','public'].index(cfg.get('privacy','private')),
                    format_func=lambda k:{'private':'Privado — recomendado para o primeiro teste','unlisted':'Não listado','public':'Público'}[k],key='yt_privacy'+suffix)
                kids=st.checkbox('Conteúdo feito para crianças',value=cfg.get('made_for_kids',False),key='yt_kids'+suffix)
                synthetic=st.checkbox('Contém conteúdo alterado ou sintético que deve ser declarado ao YouTube',value=cfg.get('contains_synthetic_media',True),key='yt_synthetic'+suffix)
                uploaded=st.file_uploader('Thumbnail JPG ou PNG — até 2 MB',type=['jpg','jpeg','png'],key='yt_thumbnail'+suffix)
                thumb=cfg.get('thumbnail','')
                if uploaded:
                    try:thumb=service.save_thumbnail(uploaded.getvalue(),store)
                    except PublishError as exc:st.warning(str(exc));thumb=''
                if thumb:st.caption('Thumbnail selecionada e salva para este canal.')
                auto=st.checkbox('Enviar automaticamente após gerar um novo vídeo neste canal',value=cfg.get('auto_upload',False),
                    disabled=not cfg.get('connected'),key='yt_auto'+suffix)
                skill_auto=st.checkbox('Autorizar envio automático de vídeos completos da Skill',value=cfg.get('skill_auto_upload',False),disabled=not cfg.get('connected'),key='yt_skill_auto'+suffix)
                st.caption('A Skill precisa estar no modo Enviar automaticamente para usar essa autorização. Cada ângulo carrega seu pacote e thumbnail, sem os campos manuais acima. Commons exige revisão manual.')
                st.caption('O título automático será o título da nova geração. Descrição, tags e thumbnail vêm destes campos: revise para cada vídeo. Recuperações antigas não passam a publicar automaticamente. A fila da Skill usa uma autorização separada abaixo. Vídeos com Commons exigem envio manual após revisão.')
                if st.button('Salvar configurações de postagem deste canal',key='yt_save'):
                    if auto and (not description.strip() or not thumb):st.warning('Para ativar, informe descrição e thumbnail.')
                    else:
                        cfg={**cfg,'description':description,'tags':tags,'privacy':privacy,'made_for_kids':kids,'thumbnail':thumb,'auto_upload':auto,'skill_auto_upload':skill_auto,'contains_synthetic_media':synthetic}
                        store.save_connection(channel,cfg);st.success('Configurações salvas para este canal.')
                # Capture persisted settings only: queued projects never change destination on rerun.
                cfg=store.connection(channel)
                if cfg.get('connected') and cfg.get('auto_upload') and all(k in cfg for k in ('description','tags','thumbnail','privacy','made_for_kids')):
                    params.youtube_publication={k:cfg[k] for k in ('youtube_channel_id','description','tags','thumbnail','privacy','made_for_kids','auto_upload')}
                    params.youtube_publication['channel_id']=channel
                    params.youtube_publication['contains_synthetic_media']=cfg.get('contains_synthetic_media',True)
            with panels[2]:
                st.markdown('**3 · Validar e enviar um vídeo já gerado**')
                files=sorted([p for p in Path(utils.task_dir()).glob('*/final-*.mp4') if p.is_file() and not p.is_symlink()],key=lambda p:p.stat().st_mtime,reverse=True)[:100]
                if files:
                    linked=[]
                    for path in files:
                        packet=path.parent/'youtube-package.json'
                        if packet.is_file():linked.append(path)
                    if linked:st.info('Há vídeos com pacote da Skill. As postagens preparadas automaticamente aparecem no histórico abaixo; não é necessário copiar seus metadados para estes campos manuais.')
                    selected=st.selectbox('Vídeo final salvo',files,format_func=lambda p:p.parent.name+' / '+p.name,key='yt_video')
                    st.caption('Preparar verifica metadados e créditos, sem enviar. Enviar / retomar, no histórico, inicia o upload com a privacidade escolhida. A verificação técnica completa ocorre antes do envio.')
                    reviewed=st.checkbox('Revisei o vídeo, os direitos de uso e os dados desta postagem',key='yt_reviewed')
                    if st.button('Preparar postagem — sem enviar',key='yt_prepare',disabled=not (cfg.get('connected') and reviewed)):
                        try:
                            job=service.prepare(channel,selected,title,description,tags,thumb,privacy,kids,store=store,contains_synthetic_media=synthetic)
                            st.success('Postagem salva: '+job['state']+'. Confira o histórico abaixo para enviar.')
                        except (ValueError,OSError) as exc:st.warning(str(exc))
                    notice=selected.parent/'youtube-publication-status.json'
                    if notice.is_file():
                        from app.services.youtube_publish.store import read
                        st.warning(read(notice,{}).get('error','Postagem requer revisão'))
                else:st.info('Nenhum vídeo final encontrado. Gere um vídeo para preparar a primeira postagem.')
            with panels[3]:
                history(channel)
