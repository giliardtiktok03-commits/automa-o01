import hashlib
import io
import subprocess
from pathlib import Path
from uuid import uuid4
from PIL import Image
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic
from .contracts import ArchiveError
from .network import safe_url


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root,relative):
    root=Path(root).resolve()
    path=(root/relative).resolve()
    if not path.is_relative_to(root):raise ArchiveError('Caminho de arquivo fora do projeto')
    return path


def download(candidate,folder,transport):
    transport.check()
    safe_url(candidate.download_url)
    raw=transport.get(candidate.provider,candidate.download_url,max_bytes=transport.settings.max_file_mb*1024*1024)
    transport.check()
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    temporary=folder/(uuid4().hex+'.partial')
    write_bytes_atomic(temporary,raw)
    try:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height>60_000_000 or min(image.size)<64:raise ArchiveError('Imagem com tamanho inválido')
                image.load()
                out=io.BytesIO()
                image.convert('RGB').save(out,format='PNG')
                content,extension=out.getvalue(),'.png'
        except (OSError,ValueError):
            if raw.startswith(b'%PDF-'):
                try:import fitz
                except ImportError:raise ArchiveError('PDF preservado apenas no registro; conversão de páginas requer PyMuPDF, não instalado') from None
                with fitz.open(stream=raw,filetype='pdf') as document:
                    if not len(document) or document.is_encrypted:raise ArchiveError('Documento PDF inválido ou protegido')
                    content,extension=document[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).tobytes('png'),'.png'
            elif candidate.media_type=='video' and (b'ftyp' in raw[:32] or raw.startswith(b'\x1aE\xdf\xa3')):
                # Validate a real decoded frame, not extension/content-type supplied remotely.
                result=subprocess.run([utils.get_ffmpeg_binary(),'-v','error','-i',str(temporary),'-frames:v','1','-f','null','-'],capture_output=True,timeout=30)
                if result.returncode:raise ArchiveError('Filmagem corrompida ou não decodificável')
                content,extension=raw,'.webm' if raw.startswith(b'\x1aE\xdf\xa3') else '.mp4'
            else:raise ArchiveError('Arquivo não é imagem/documento/filmagem válido; HTML e extensões falsas são rejeitados') from None
        transport.check()
        digest=hashlib.sha256(content).hexdigest()
        target=folder/(digest+extension)
        if not target.exists():write_bytes_atomic(target,content)
        return target,digest
    finally:temporary.unlink(missing_ok=True)
