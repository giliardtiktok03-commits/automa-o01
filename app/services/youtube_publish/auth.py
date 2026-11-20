"""Installed desktop OAuth on loopback, separately authorized for each MPT channel."""
import json
import logging
import re
import threading
from urllib.parse import urlparse
from filelock import FileLock
from .store import Store,PublishError,channel_key,put,read

# Official scope required by videos.update as well as uploads and channel lookup.
SCOPES=['https://www.googleapis.com/auth/youtube.force-ssl']
API='https://www.googleapis.com/youtube/v3'
_pending={}
_guard=threading.Lock()


def dependencies():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:raise PublishError('Instale requirements-youtube.txt no ambiente Python do MPT') from None


def client_config(raw):
    try:
        if len(raw)>64*1024:raise ValueError()
        data=json.loads(raw);item=data['installed']
        if not item.get('client_id') or not item.get('client_secret'):raise ValueError()
        # Only Google's real OAuth endpoints, never a URL supplied by an arbitrary upload.
        if item['auth_uri']!='https://accounts.google.com/o/oauth2/auth' or item['token_uri']!='https://oauth2.googleapis.com/token':raise ValueError()
        return {'installed':item}
    except (KeyError,TypeError,ValueError):raise PublishError('Envie o JSON OAuth do Google do tipo Aplicativo para computador') from None


def identity(session):
    response=session.get(API+'/channels',params={'part':'snippet','mine':'true'},timeout=30,allow_redirects=False)
    if response.status_code!=200:raise PublishError('Não foi possível confirmar o canal. Confira a YouTube Data API e as permissões OAuth')
    rows=response.json().get('items',[])
    if len(rows)!=1 or not re.fullmatch(r'UC[\w-]{22}',rows[0].get('id','')):
        raise PublishError('A autorização precisa identificar exatamente um canal do YouTube')
    return {'youtube_channel_id':rows[0]['id'],'youtube_channel_name':rows[0].get('snippet',{}).get('title','')}


def session(channel,store=None):
    dependencies();store=store or Store()
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession,Request
    with FileLock(str(store.secret_path(channel))+'.lock',timeout=30):
        data=read(store.secret_path(channel))
        if not data:raise PublishError('Conecte este canal ao Google antes de enviar')
        try:
            if data.get('token_uri')!='https://oauth2.googleapis.com/token':raise ValueError()
            credentials=Credentials.from_authorized_user_info(data,SCOPES)
            if not credentials.valid:
                credentials.refresh(Request())
                put(store.secret_path(channel),json.loads(credentials.to_json()),private=True)
        except Exception:raise PublishError('Não foi possível renovar a autorização Google. Confira a conexão de rede e reconecte o canal se a permissão expirou ou foi revogada') from None
    return AuthorizedSession(credentials)


def status(channel):
    with _guard:return dict(_pending.get(channel_key(channel),{}))


def connect(channel,raw,store=None):
    dependencies();channel_key(channel);store=store or Store();config=client_config(raw)
    with _guard:
        if _pending.get(channel,{}).get('state') in {'starting','waiting'}:raise PublishError('Já existe uma conexão Google em andamento para este canal')
        _pending[channel]={'state':'starting'}
    def run():
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import AuthorizedSession
            # OAuth callback URLs contain codes: never log request paths.
            logging.getLogger('google_auth_oauthlib.flow').setLevel(logging.WARNING)
            with FileLock(str(store.secret_path(channel))+'.connect.lock',timeout=0):
                flow=InstalledAppFlow.from_client_config(config,SCOPES,autogenerate_code_verifier=True)
                original=flow.authorization_url
                def authorization_url(**kwargs):
                    url,state=original(**kwargs)
                    with _guard:_pending[channel]={'state':'waiting','url':url}
                    return url,state
                flow.authorization_url=authorization_url
                credentials=flow.run_local_server(host='127.0.0.1',port=0,open_browser=False,
                    timeout_seconds=300,authorization_prompt_message=None,
                    success_message='Autorizacao recebida. Volte ao MPT para conferir o canal.',
                    access_type='offline',prompt='consent')
                if not credentials.refresh_token:raise PublishError('Google não forneceu autorização duradoura; tente conectar novamente')
                with AuthorizedSession(credentials) as api:account=identity(api)
                old=store.connection(channel)
                if old.get('youtube_channel_id') and old['youtube_channel_id']!=account['youtube_channel_id']:
                    raise PublishError('O Google autorizou outro canal. Desconecte o vínculo antigo antes de trocar')
                with FileLock(str(store.secret_path(channel))+'.lock',timeout=30):
                    put(store.secret_path(channel),json.loads(credentials.to_json()),private=True)
                store.save_connection(channel,{**old,**account,'connected':True})
                with _guard:_pending[channel]={'state':'connected'}
        except Exception as exc:
            error=str(exc) if isinstance(exc,PublishError) else 'Conexão não concluída. Confira o consentimento Google e tente novamente (prazo: 5 minutos)'
            with _guard:_pending[channel]={'state':'failed','error':error}
    threading.Thread(target=run,name='youtube-oauth',daemon=True).start()


def disconnect(channel,store=None):
    store=store or Store()
    if status(channel).get('state') in {'starting','waiting'}:raise PublishError('Aguarde a conexão em andamento terminar antes de desconectar')
    with FileLock(str(store.secret_path(channel))+'.lock',timeout=30):store.secret_path(channel).unlink(missing_ok=True)
    old=store.connection(channel);store.save_connection(channel,{**old,'connected':False,'auto_upload':False})
    with _guard:_pending.pop(channel,None)
