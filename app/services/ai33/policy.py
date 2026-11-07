"""Production policy shared by legacy synthetic-image entry points."""


class SyntheticImagePolicyError(ValueError):
    pass


def reject_legacy_generation():
    raise SyntheticImagePolicyError(
        "Novas imagens sintéticas usam exclusivamente AI33.Pro. "
        "Selecione AI33.Pro ou o modo misto; arquivos antigos continuam utilizáveis."
    )
