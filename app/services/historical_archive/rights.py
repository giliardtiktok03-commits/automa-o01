"""Conservative reuse policy, separate from editorial relevance."""
import re
from urllib.parse import urlparse


def assess(candidate):
    text = ' '.join([candidate.rights_statement, candidate.license_url]).lower()
    if re.search(r'all rights reserved|todos os direitos|noncommercial|non-commercial|no derivatives|no.derivatives|by-nc|by-nd|by-nc-nd|not (?:in the )?public domain|permission required|\brestricted\b', text):
        return 'restricted', 'Restrição incompatível com reutilização automática em canal monetizado'
    url = urlparse(candidate.license_url)
    if url.scheme == 'https' and url.hostname in {'creativecommons.org','www.creativecommons.org'}:
        path = url.path.rstrip('/')
        if re.fullmatch(r'/publicdomain/(zero/1\.0|mark/1\.0)',path):
            return 'rights_cleared', 'Declaração explícita CC0 ou Public Domain Mark'
        if re.fullmatch(r'/licenses/by(?:-sa)?/(?:1\.0|2\.0|2\.5|3\.0|4\.0)',path):
            if candidate.creator and candidate.attribution:
                return 'rights_cleared', 'Licença CC BY/SA explícita; preservar crédito e condições da licença'
            return 'needs_review', 'Item ignorado: licença exige atribuição, mas autoria/crédito estão incompletos'
    statement=candidate.rights_statement.strip().rstrip('.').lower()
    if re.fullmatch(r'public domain|domínio público|this (?:image|work|item) is in the public domain',statement):
        return 'rights_cleared','Registro declara domínio público explicitamente'
    return 'needs_review','Item ignorado: direitos ausentes ou insuficientes; instituição pública e acesso gratuito não liberam a obra'
