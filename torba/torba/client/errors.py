class InvalidPasswordError(Exception):

    def __init__(self):
        super().__init__("Password is invalid.")


class InsufficientFundsError(Exception):
    pass
