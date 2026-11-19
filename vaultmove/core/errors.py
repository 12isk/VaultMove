"""Exception hierarchy for the engine."""


class VaultMoveError(Exception):
    """Base class for all engine errors."""


class ConfigError(VaultMoveError):
    pass


class VaultNotConnected(VaultMoveError):
    """The backup drive is not present. Nothing is written anywhere."""


class VaultInvalid(VaultMoveError):
    """Destination is not a usable vault (missing marker, wrong UUID, non-empty folder...)."""


class VaultBusy(VaultMoveError):
    """Another VaultMove process holds the vault lock."""


class VaultFull(VaultMoveError):
    """Not enough free space on the backup drive."""


class SameDriveRefused(VaultMoveError):
    """Vault and a source are on the same physical disk and no override was given."""


class OverlapRefused(VaultMoveError):
    """Vault is inside a source or a source is inside the vault."""


class Cancelled(VaultMoveError):
    pass


class SourceReadError(VaultMoveError):
    """Reading a source file failed (locked, vanished, permission...)."""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


class VaultWriteError(VaultMoveError):
    """Writing to the vault failed."""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


class VerifyFailed(VaultMoveError):
    """A hash verification did not match."""


class ChangedDuringCopy(VaultMoveError):
    """The source changed while it was being copied."""
