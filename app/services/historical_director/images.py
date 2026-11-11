"""Content-addressed, metadata-free thumbnail references; never executable input."""
import hashlib
import io
import warnings
from pathlib import Path
from PIL import Image, ImageOps
from app.models.historical_director import ImageRef
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic


def root():
    return Path(utils.storage_dir('historical-director/references',create=True)).resolve()


def location(image_id):
    ImageRef(image_id=image_id,width=64,height=64)
    path=root()/(image_id+'.png')
    if path.is_symlink() or not path.resolve().is_relative_to(root()):
        raise ValueError('Referência visual fora do diretório permitido')
    return path


def store(raw, max_mb=10):
    if not raw or len(raw)>max_mb*1024*1024:
        raise ValueError(f'Thumbnail deve ter até {max_mb} MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {'JPEG','PNG','WEBP'} or getattr(image,'n_frames',1)!=1:
                    raise ValueError('Use JPG, PNG ou WebP sem animação')
                if min(image.size)<64 or image.width*image.height>20000000:
                    raise ValueError('Imagem deve ter ao menos 64 px e no máximo 20 megapixels')
                image.load()
                cleaned=ImageOps.exif_transpose(image).convert('RGB')
                cleaned.thumbnail((2048,2048))
                out=io.BytesIO()
                cleaned.save(out,format='PNG')
                body=out.getvalue()
                ref=ImageRef(image_id=hashlib.sha256(body).hexdigest(),width=cleaned.width,height=cleaned.height)
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValueError('Thumbnail inválida ou grande demais para decodificar') from None
    target=location(ref.image_id)
    if not target.exists():write_bytes_atomic(target,body)
    return ref


def upload(raw_files,max_mb=10):
    if len(raw_files)>3:raise ValueError('Envie no máximo 3 thumbnails de referência')
    refs=[store(raw,max_mb) for raw in raw_files]
    if len({r.image_id for r in refs})!=len(refs):raise ValueError('Thumbnails repetidas por conteúdo')
    return refs


def read(ref):
    ref=ImageRef.model_validate(ref)
    data=location(ref.image_id).read_bytes()
    if len(data)>20*1024*1024 or hashlib.sha256(data).hexdigest()!=ref.image_id:
        raise ValueError('A referência visual foi alterada ou excedeu o limite')
    return data
