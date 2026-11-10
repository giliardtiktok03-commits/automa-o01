import html
import re


def text(value):
    if isinstance(value,str):return html.unescape(re.sub('<[^>]+>',' ',value)).strip()
    if isinstance(value,list):return '; '.join(text(v) for v in value)
    if isinstance(value,dict):return '; '.join(text(v) for v in value.values())
    return '' if value is None else str(value)


def media(value):
    value=text(value).lower()
    if any(w in value for w in ('audio/','sound recording','.mp3','.wav')):return 'audio'
    if any(w in value for w in ('video','moving image','motion picture','mp4','webm','film')):return 'video'
    if any(w in value for w in ('map','cartograph','diagram')):return 'map'
    if any(w in value for w in ('document','manuscript','newspaper','pdf','text','written record','book')):return 'document'
    return 'photograph'


def upgrade_url(value):
    # Older institution metadata often publishes HTTP links; use HTTPS on the
    # same official host, never an insecure request or arbitrary replacement.
    from urllib.parse import urlparse,urlunparse
    if not isinstance(value,str):return ''
    parsed=urlparse(value)
    host=parsed.hostname or ''
    if parsed.scheme=='http' and any(host==d or host.endswith('.'+d) for d in ('loc.gov','archives.gov','wikimedia.org')):
        return urlunparse(parsed._replace(scheme='https'))
    return value
