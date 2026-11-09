"""Shared Flow exceptions, including when the browser worker runs as __main__."""

class FlowError(ValueError):
    def __init__(self,message,*,key=None):
        super().__init__(message)
        self.key=key


class FlowRefusal(FlowError):
    pass
