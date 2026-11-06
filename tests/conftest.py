"""Test-only provider stub so deterministic business logic can be tested offline."""
import sys
import types

try:  # pragma: no cover - only used when optional SDK is not installed in the test runtime
    import sarvamai  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("sarvamai")

    class SarvamAI:  # noqa: D101
        def __init__(self, *args, **kwargs):
            raise RuntimeError("SarvamAI SDK is required only for live provider calls")

    stub.SarvamAI = SarvamAI
    sys.modules["sarvamai"] = stub
