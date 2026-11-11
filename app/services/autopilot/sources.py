"""Bounded public HTTPS source reader. Never executes page text or sends API keys."""
import hashlib
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit, urljoin

import requests

from app.services.autopilot.recovery import RecoveryBlocked

MAX_BYTES = 1024 * 1024
MAX_TEXT = 60000


def canonical(url):
    try:
        p = urlsplit(url)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
            raise ValueError()
        host = p.hostname.encode('idna').decode('ascii').lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        return urlunsplit(('https', host, p.path or '/', p.query, ''))
    except (ValueError, UnicodeError):
        raise RecoveryBlocked("Fonte com endereço HTTPS inválido") from None


def allowed(url, domains):
    host = urlsplit(canonical(url)).hostname
    return not domains or any(host == d or host.endswith('.' + d) for d in domains)


def check_public(url):
    host = urlsplit(canonical(url)).hostname
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise RecoveryBlocked("A fonte não resolve para um endereço público permitido") from None


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript', 'nav', 'footer', 'svg', 'template'}:
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'nav', 'footer', 'svg', 'template'}:
            self.skip = max(0, self.skip - 1)
    def handle_data(self, value):
        if not self.skip and value.strip():
            self.parts.append(value.strip())


def normalize(value):
    return re.sub(r'\s+', ' ', value).strip()


def fetch(url, domains=()):
    original = canonical(url)
    current = original
    for redirect in range(4):
        if not allowed(current, domains):
            raise RecoveryBlocked("A fonte saiu dos domínios configurados para o canal")
        check_public(current)
        try:
            with requests.get(current, stream=True, timeout=(10, 25), allow_redirects=False,
                              auth=lambda request: request, headers={'User-Agent': 'MPT-Autopilot/1.0 (editorial research)', 'Accept': 'text/html,text/plain'}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    if not location or redirect == 3:
                        raise RecoveryBlocked("Redirecionamento da fonte não pôde ser confirmado")
                    current = canonical(urljoin(current, location))
                    continue
                if response.status_code != 200:
                    raise RecoveryBlocked("Fonte indisponível; revise a pesquisa antes de gerar roteiro")
                content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
                if content_type not in {'text/html', 'text/plain', 'application/xhtml+xml'}:
                    raise RecoveryBlocked("A fonte não oferece texto legível nesta entrega")
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise RecoveryBlocked("A fonte excedeu o limite de leitura")
                encoding = response.encoding or 'utf-8'
        except requests.RequestException:
            raise RecoveryBlocked("Não foi possível ler a fonte; nenhuma referência foi inventada") from None
        try:
            raw = body.decode(encoding, errors='replace')
        except LookupError:
            raw = body.decode('utf-8', errors='replace')
        if content_type != 'text/plain':
            parser = Text()
            parser.feed(raw)
            raw = ' '.join(parser.parts)
        text = normalize(raw)[:MAX_TEXT]
        if len(text) < 150:
            raise RecoveryBlocked("Fonte sem conteúdo suficiente para sustentar a pesquisa")
        return {'url': original, 'resolved_url': current, 'text': text,
                'sha256': hashlib.sha256(text.encode()).hexdigest()}
    raise RecoveryBlocked("Não foi possível confirmar a fonte")
