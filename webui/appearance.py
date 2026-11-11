"""Session-local presentation with an installation preference in MPT's existing config."""
from pathlib import Path
import streamlit as st
from app.config import config

OPTIONS=('light','dark','system')
LABELS={'light':'Claro','dark':'Escuro','system':'Seguir o sistema'}
KEY='mpt_appearance_theme'
PALETTES={
    'light': {'bg':'#ffffff','panel':'#f8fafc','control':'#f1f5f9','text':'#172033','muted':'#526176',
              'border':'#cbd5e1','link':'#0759b8','hover':'#e2e8f0','accent':'#0759b8','accent-text':'#ffffff'},
    'dark': {'bg':'#101722','panel':'#182232','control':'#202d40','text':'#edf2fa','muted':'#b2c0d4',
             'border':'#52637b','link':'#8fc5ff','hover':'#2b3c54','accent':'#79b7ff','accent-text':'#101722'},
}


def normalize(value):
    return value if isinstance(value,str) and value in OPTIONS else 'light'


def selected():
    settings=config.snapshot_config_with_pending(config.ui)
    return normalize(st.session_state.get(KEY,settings.get('appearance_theme','light')))


def _variables(mode):
    return ':root {color-scheme:'+mode+';' + ''.join('--mpt-'+k+':'+v+';' for k,v in PALETTES[mode].items())+'}'


def apply():
    mode=selected()
    palette=_variables('light' if mode=='system' else mode)
    if mode=='system':palette+='\n@media (prefers-color-scheme: dark) {'+_variables('dark')+'}'
    style=Path(__file__).with_name('appearance.css').read_text(encoding='utf-8')
    st.html('<style>'+palette+'\n'+style+'</style>')


def _changed():
    value=normalize(st.session_state.get(KEY))
    config.update_config_nonblocking(config.ui,'appearance_theme',value)
    config.try_save_config()


def render_control():
    if KEY not in st.session_state:st.session_state[KEY]=selected()
    with st.popover('Aparência',icon=':material/contrast:',width='content'):
        with st.container(key='appearance_controls'):
            st.selectbox('Tema do aplicativo',OPTIONS,format_func=lambda mode:LABELS[mode],key=KEY,on_change=_changed)
            st.caption('A preferência é salva nesta instalação do MPT. O tema não altera vídeos, legendas ou thumbnails.')
