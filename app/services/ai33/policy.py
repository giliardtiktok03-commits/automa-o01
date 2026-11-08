"""Production policy shared by legacy synthetic-image entry points."""


class SyntheticImagePolicyError(ValueError):
    pass


def reject_legacy_generation():
    raise SyntheticImagePolicyError(
        "Novas imagens sintéticas usam Runware ou AI33.Pro explicitamente habilitada. "
        "Selecione Runware ou o modo misto; arquivos antigos continuam utilizáveis."
    )
