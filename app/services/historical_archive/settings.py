from app.config import config
from .contracts import ArchiveSettings

PREFIX = 'historical_archive_'


def mapping():
    return config.snapshot_config_with_pending(config.app)


def enabled():
    return bool(mapping().get(PREFIX+'enabled',False))


def load(values=None):
    values = mapping() if values is None else values
    fields={key: values[PREFIX+key] for key in ArchiveSettings.model_fields if PREFIX+key in values}
    # Earlier draft modes never impose an approval gate: production is automatic.
    if fields.get('mode') in {'manual_review','historical_first'}:fields['mode']='historical_plus_stock'
    return ArchiveSettings.model_validate(fields)
