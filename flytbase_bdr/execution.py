"""Explicit, thread-local permission for network execution. Default is read-only."""
from contextlib import contextmanager
from contextvars import ContextVar
import httpx
from .provider import ProviderError

_APPROVED = ContextVar("flytbase_live_execution_approved", default=False)
_PHASE = ContextVar("flytbase_execution_phase", default="repair")
_FREE_QUOTA = ContextVar("flytbase_confirmed_free_quota", default=False)
_ALLOWANCE = ContextVar("flytbase_new_run_allowance", default="")


class LiveExecutionBlocked(ProviderError):
    pass


@contextmanager
def approved_live_execution(approved=False, *, phase="repair", confirmed_free_quota=False, allowance_id=""):
    if phase not in {"repair", "demo", "new_run"}:
        raise LiveExecutionBlocked("Unknown execution phase blocked. Choose repair or demo.")
    if not approved:
        raise LiveExecutionBlocked("Live execution is locked. Review the offline plan and explicitly approve this execution first.")
    if phase == "new_run" and (not allowance_id or not confirmed_free_quota):
        raise LiveExecutionBlocked("New-run execution requires a specific approved allowance and free-quota confirmation.")
    token = _APPROVED.set(True)
    phase_token = _PHASE.set(phase)
    quota_token = _FREE_QUOTA.set(bool(confirmed_free_quota))
    allowance_token = _ALLOWANCE.set(allowance_id)
    try:
        yield
    finally:
        _ALLOWANCE.reset(allowance_token)
        _FREE_QUOTA.reset(quota_token)
        _PHASE.reset(phase_token)
        _APPROVED.reset(token)


def require_live_execution(client=None):
    # Offline HTTP contract tests are not network access and spend no credits.
    if client is not None and isinstance(getattr(client, "_transport", None), httpx.MockTransport):
        return
    if not _APPROVED.get():
        raise LiveExecutionBlocked("Read-only mode blocked a network request before dispatch or usage reservation. Explicit live approval is required.")


def current_execution_phase() -> str:
    """Return the phase scoped to this thread; defaults to repair for safety."""
    return _PHASE.get()


def free_quota_confirmed():
    return _FREE_QUOTA.get()


def current_allowance_id():
    return _ALLOWANCE.get()
