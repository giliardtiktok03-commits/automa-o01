"""Independent official archive providers. No requests at import time."""
from .loc import LOCProvider
from .nara import NARAProvider
from .wikimedia import WikimediaProvider


def providers(transport,settings,credentials):
    result=[]
    if settings.loc_enabled:result.append(LOCProvider(transport))
    if settings.nara_enabled:result.append(NARAProvider(transport,credentials.get('nara_api_key','')))
    if settings.wikimedia_enabled:result.append(WikimediaProvider(transport))
    return result
