"""Stable error codes for model/scenario validation (M0 contract)."""


class ShadowBoxError(Exception):
    """Base error with a stable machine-readable code."""

    code: str = "E_UNKNOWN"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RefError(ShadowBoxError):
    code = "E_REF"


class CycleError(ShadowBoxError):
    code = "E_CYCLE"


class SchemaError(ShadowBoxError):
    code = "E_SCHEMA"


class TooLargeError(ShadowBoxError):
    code = "E_TOO_LARGE"


class UnsafeYamlError(ShadowBoxError):
    code = "E_UNSAFE_YAML"


class SeedMismatchWarning(ShadowBoxError):
    code = "E_SEED_MISMATCH"


class ExistsError(ShadowBoxError):
    code = "E_EXISTS"
