"""Persistent project ceilings across probes, runs and retries. Unknown usage stays reserved."""
import json
import threading
import uuid
import time
from pathlib import Path
from contextlib import contextmanager
from .provider import QuotaExhausted
from .evidence import now

_LOCK = threading.RLock()


class ProjectBudget:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.run_path() / "project_budget.json"

    @contextmanager
    def locked(self):
        """Serialize ledger changes across both UI threads and separate CLI processes."""
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = (self.path.parent / ".project_budget.lock").open("a+b")
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            import os
            if os.name == "nt":
                import msvcrt
                deadline = time.monotonic() + 10
                while True:
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            handle.close()
                            raise QuotaExhausted("Project budget is locked by another process; no request sent.") from None
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    handle.close()
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    handle.close()

    def read(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise QuotaExhausted("Project budget ledger is unreadable; live work stopped, ledger not reset.") from None
        return {"created_at": now(), "ceilings": {"groq": self.settings.project_max_groq_tokens, "tavily": self.settings.project_max_tavily_credits}, "entries": []}

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def reserve(self, provider, amount, purpose, *, run_id="", request_window=None):
        with self.locked():
            data = self.read()
            if provider == "groq" and request_window:
                from datetime import datetime, timezone
                from .provider import ProjectWindowWait
                stamp = datetime.now(timezone.utc).timestamp()
                recent = []
                for entry in data["entries"]:
                    if entry["provider"] == "groq" and entry.get("request_window"):
                        age = stamp - datetime.fromisoformat(entry["at"]).timestamp()
                        if 0 <= age < 61:
                            recent.append((entry, age))
                window_used = sum(e["actual"] if e["actual"] is not None else e["reserved"] for e, _ in recent)
                if recent and (window_used + amount > request_window["tpm"] or len(recent) >= request_window["rpm"]):
                    raise ProjectWindowWait(max(.1, 61 - max(age for _, age in recent)))
            from .execution import current_execution_phase
            if current_execution_phase() == "new_run":
                from .execution import current_allowance_id
                from .run_allowance import reserve_entry
                ticket = reserve_entry(data, provider, amount, purpose, run_id, current_allowance_id(), request_window)
                self.write(data)
                return ticket
            demo = data.get("one_time_demo") if current_execution_phase() == "demo" else None
            if demo:
                if demo["state"] != "started" or not run_id or demo.get("run_id") != run_id:
                    raise QuotaExhausted("One-time demo is not bound to this run; no request sent.")
                if provider == "groq" and demo.get("sequence") == 4:
                    today = [e for e in data["entries"] if e["provider"] == "groq" and e.get("at", "").startswith(now()[:10])]
                    used_today = sum(e["actual"] if e["actual"] is not None else e["reserved"] for e in today)
                    emergency = data.get("phase_limits", {}).get("emergency_reserve", 7759)
                    if used_today + amount + emergency > 200000 or len(today) >= 990:
                        raise QuotaExhausted("Conservative daily Groq token/request allowance exhausted; no automatic daily retry.")
                entries = [e for e in data["entries"] if e.get("allowance_id") == demo["id"] and e["provider"] == provider]
                consumed = sum(e["actual"] if e["actual"] is not None else e["reserved"] for e in entries)
                attempts = demo["limits"]["groq_requests" if provider == "groq" else purpose + "_requests"]
                if provider == "tavily":
                    entries = [e for e in entries if e["purpose"] == purpose]
                if (len(entries) >= attempts or amount <= 0
                        or consumed + amount > demo["limits"][provider]):
                    raise QuotaExhausted(f"One-time {provider} demo allowance/request limit exhausted; no retry run or paid fallback.")
                ticket = uuid.uuid4().hex
                data["entries"].append({"id": ticket, "at": now(), "provider": provider, "purpose": purpose,
                                        "reserved": amount, "actual": None, "status": "reserved_or_usage_unavailable",
                                        "allowance_id": demo["id"], "run_id": run_id,
                                        **({"request_window": request_window} if request_window else {})})
                self.write(data)
                return ticket
            ceiling = min(data["ceilings"][provider], getattr(self.settings, "project_max_groq_tokens" if provider == "groq" else "project_max_tavily_credits"))
            if provider == "groq" and data.get("phase_limits"):
                from .execution import current_execution_phase
                phase = current_execution_phase()
                phase_limits = data["phase_limits"]
                if phase == "repair":
                    ceiling = min(ceiling, phase_limits["repair_cumulative_cap"])
                elif phase == "demo":
                    # A fresh demo is separately approved by explicit context; retain
                    # emergency allowance under all ordinary execution paths.
                    ceiling = min(ceiling, data["ceilings"]["groq"] - phase_limits["emergency_reserve"])
            consumed = sum(e["actual"] if e["actual"] is not None else e["reserved"] for e in data["entries"] if e["provider"] == provider)
            if consumed + amount > ceiling:
                raise QuotaExhausted(f"Project {provider} ceiling would be exceeded: {consumed:g} used/reserved + {amount:g} requested > {ceiling:g}. Progress preserved; no limit raised.")
            ticket = uuid.uuid4().hex
            data["entries"].append({"id": ticket, "at": now(), "provider": provider, "purpose": purpose,
                                    "reserved": amount, "actual": None, "status": "reserved_or_usage_unavailable",
                                    **({"request_window": request_window} if request_window else {})})
            self.write(data)
            return ticket

    def prepare_final_demo(self):
        """Append the expressly requested one-run envelope, never reset old limits/entries."""
        with self.locked():
            data = self.read()
            if data.get("one_time_demo"):
                return data["one_time_demo"]  # Idempotent; never replenish a spent envelope.
            if not self.path.exists():
                raise ValueError("Final demo requires the existing historical ledger; no new quota ledger created.")
            backup = self.path.with_name("project_budget.before_final_demo.json")
            if backup.exists():
                raise ValueError("Final-demo backup already exists; no allowance recreated or overwritten.")
            backup.write_bytes(self.path.read_bytes())
            data["one_time_demo"] = {
                "id": "final-demo-" + uuid.uuid4().hex[:12], "created_at": now(),
                "state": "prepared", "run_id": "", "approval": "User explicitly requested one-time demo allowance; live launch approval still required",
                "limits": {"groq": 60000, "tavily": 16, "groq_requests": 24,
                           "search_requests": 10, "extract_requests": 5, "control_requests": 2},
                "dashboard_basis": {"source": "user-verified dashboard; not queried by this preparation",
                                    "model": "openai/gpt-oss-120b", "groq_daily_limit": 200000,
                                    "groq_used_today_approx": 23200, "groq_tpm": 8000,
                                    "tavily_plan_limit": 1000, "tavily_used": 28},
                "note": "Supplemental one-run envelope only. Legacy ceilings, repair/demo/emergency records and every historical entry retained. No billing action."
            }
            self.write(data)
            return data["one_time_demo"]

    def prepare_second_demo(self):
        """Explicitly approved second envelope; old run, requests and ledger remain immutable.

        This does not verify real-time provider quota or contact either provider.
        The caller must confirm free-only dashboard status before live launch.
        """
        with self.locked():
            data = self.read()
            old = data.get("one_time_demo")
            if not old or old.get("state") != "finished" or not old.get("run_id"):
                raise ValueError("First demo must have finished; ledger unchanged.")
            history = data.get("demo_history", [])
            if history or old.get("sequence") == 2:
                raise ValueError("Second-demo allowance already created; cannot replenish it.")
            if not self.path.exists():
                raise ValueError("Existing budget ledger required.")
            backup = self.path.with_name("project_budget.before_second_demo.json")
            if backup.exists():
                raise ValueError("Second-demo backup already exists; refusing to overwrite it.")
            # Save exact ledger before mutation. Do not reuse unused first-demo credits.
            backup.write_bytes(self.path.read_bytes())
            data["demo_history"] = [old.copy()]
            data["one_time_demo"] = {
                "id": "second-demo-" + uuid.uuid4().hex[:12],
                "sequence": 2, "created_at": now(), "state": "prepared", "run_id": "",
                "approval": "User requested a second free-only real run; live launch separately requires explicit approval",
                "limits": {"groq": 45000, "tavily": 12, "groq_requests": 24,
                           "search_requests": 8, "extract_requests": 4, "control_requests": 2},
                "dashboard_basis": {"source": "previous user screenshots; not current live quota verification",
                                    "model": "openai/gpt-oss-120b", "groq_tpm": 8000,
                                    "must_recheck_dashboard_before_launch": True},
                "note": "Second one-run supplemental cap; prior envelope and all history retained. No billing or API action."
            }
            self.write(data)
            return data["one_time_demo"]

    def prepare_third_demo(self):
        """Prepare one explicitly requested fresh free-only run, retaining all history.

        This is an application-side allowance, not confirmation of provider quota.
        No tokens or searches are spent by this method.
        """
        with self.locked():
            data = self.read()
            old = data.get("one_time_demo")
            if not old or old.get("sequence") != 2 or old.get("state") != "finished" or not old.get("run_id"):
                raise ValueError("A finished second demo is required; ledger unchanged.")
            if any(d.get("sequence") == 3 for d in data.get("demo_history", [])):
                raise ValueError("Third demo was already created; refusing to replenish it.")
            if not self.path.exists():
                raise ValueError("Existing historical ledger required.")
            backup = self.path.with_name("project_budget.before_third_demo.json")
            if backup.exists():
                raise ValueError("Third-demo backup already exists; refusing to overwrite it.")
            backup.write_bytes(self.path.read_bytes())
            data.setdefault("demo_history", []).append(old.copy())
            data["one_time_demo"] = {
                "id": "third-demo-" + uuid.uuid4().hex[:12],
                "sequence": 3, "created_at": now(), "state": "prepared", "run_id": "",
                "approval": "User explicitly requested full fresh execution and increased application allowance on 2026-11-05; separate click approves provider requests",
                "limits": {"groq": 60000, "tavily": 16, "groq_requests": 24,
                           "search_requests": 10, "extract_requests": 5, "control_requests": 2},
                "dashboard_basis": {"source": "user screenshot of November 5 activity: ~75.3k usage; not a provider quota check",
                                    "model": "openai/gpt-oss-120b", "must_recheck_actual_free_tier_limits": True},
                "note": "Single fresh execution; no paid fallback. Past entries, prior demo envelopes, cumulative ceilings and reservations preserved. Reuse of source cache does not imply reuse of generated answers."
            }
            self.write(data)
            return data["one_time_demo"]

    def prepare_fourth_demo(self):
        """Append the user-requested fourth allowance; preserve all earlier envelopes."""
        with self.locked():
            data = self.read()
            old = data.get("one_time_demo", {})
            if old.get("sequence") != 3 or old.get("state") != "finished" or not old.get("run_id"):
                raise ValueError("Finished third demo required; no allowance reset or replaced.")
            if any(d.get("sequence") == 4 for d in data.get("demo_history", [])):
                raise ValueError("Fourth allowance already exists; it cannot be replenished.")
            today_entries = [e for e in data["entries"] if e["provider"] == "groq" and e.get("at", "").startswith(now()[:10])]
            reported = sum(e["actual"] for e in today_entries if e["actual"] is not None)
            unknown = sum(e["reserved"] for e in today_entries if e["actual"] is None)
            emergency = data.get("phase_limits", {}).get("emergency_reserve", 7759)
            if reported + unknown + 62000 + emergency > 200000:
                raise ValueError("Conservative local daily accounting cannot cover 62,000 tokens plus emergency reserve. No allowance changed; inspect the current dashboards.")
            backup = self.path.with_name("project_budget.before_fourth_demo.json")
            if backup.exists():
                raise ValueError("Fourth-demo backup exists; refusing to overwrite it.")
            backup.write_bytes(self.path.read_bytes())
            data.setdefault("demo_history", []).append(old.copy())
            data["one_time_demo"] = {
                "id": "fourth-demo-" + uuid.uuid4().hex[:12], "sequence": 4,
                "created_at": now(), "state": "prepared", "run_id": "",
                "approval": "User requested fourth separate free-only preparation; no live request authorised yet",
                "limits": {"groq": 62000, "tavily": 32, "groq_requests": 30,
                           "search_requests": 12, "extract_requests": 8, "control_requests": 2},
                "quota_confirmation_required": True,
                "dashboard_basis": {"source": "official published limits and saved account snapshots, not current account verification",
                    "model": "openai/gpt-oss-120b", "groq_daily_limit": 200000, "groq_tpm": 8000,
                    "local_utc_date": now()[:10], "local_today_reported_at_preparation": reported, "local_today_unknown_reserved": unknown,
                    "minimum_confirmed_groq_free_remaining": 62000 + emergency,
                    "tavily_monthly_free_limit": 1000, "last_saved_free_credits": 962,
                    "subsequent_recorded_tavily_credits": 5, "must_recheck_dashboard_before_launch": True},
                "note": "Separate supplemental allowance; legacy ceilings, reserves, usage entries and earlier allowances preserved. No billing change."
            }
            self.write(data)
            return data["one_time_demo"]

    def optimize_fourth_demo(self):
        """Amend only the unused fourth envelope, with its prior limits retained."""
        with self.locked():
            data = self.read()
            demo = data.get("one_time_demo", {})
            if demo.get("sequence") != 4 or demo.get("state") != "prepared" or demo.get("run_id"):
                raise ValueError("Only an unused prepared fourth allowance may be amended.")
            if any(e.get("allowance_id") == demo["id"] for e in data["entries"]):
                raise ValueError("Fourth allowance already has usage; no changes permitted.")
            desired = {**demo["limits"], "tavily": 60, "search_requests": 24, "extract_requests": 12}
            if desired == demo["limits"]:
                return demo
            backup = self.path.with_name("project_budget.before_fourth_optimization.json")
            if backup.exists():
                raise ValueError("Fourth-optimization backup exists; refusing to overwrite history.")
            backup.write_bytes(self.path.read_bytes())
            previous = dict(demo["limits"])
            demo.setdefault("amendments", []).append({"at": now(), "previous_limits": previous, "new_limits": desired,
                "reason": "User requested final optimisation; retain 62000 Groq because unknown daily reservations cannot be discarded; Tavily dashboard reports 43/1000 used, PAYGO off.",
                "provider_requests": 0})
            demo["limits"] = desired
            demo["optimized_research"] = True
            demo["dashboard_basis"]["tavily_user_reported_used"] = 43
            demo["dashboard_basis"]["groq_user_reported_used_approx"] = 96800
            demo["dashboard_basis"]["current_account_balances_verified_by_app"] = False
            self.write(data)
            return demo

    def demo_summary(self):
        with self.locked():
            data = self.read()
            demo = data.get("one_time_demo")
            if not demo:
                return None
            result = dict(demo)
            for provider in ("groq", "tavily"):
                entries = [e for e in data["entries"] if e.get("allowance_id") == demo["id"] and e["provider"] == provider]
                used = sum(e["actual"] if e["actual"] is not None else e["reserved"] for e in entries)
                result[provider + "_remaining"] = max(0, demo["limits"][provider] - used)
                result[provider + "_attempts"] = len(entries)
            return result

    def start_final_demo(self, run_id):
        from .execution import current_execution_phase, require_live_execution
        require_live_execution()
        if current_execution_phase() != "demo":
            raise QuotaExhausted("One-time allowance requires explicit demo execution phase.")
        with self.locked():
            data = self.read()
            demo = data.get("one_time_demo")
            if not demo or demo["state"] != "prepared" or not run_id:
                raise QuotaExhausted("One-time demo is unavailable or already started; no second execution permitted.")
            if demo.get("quota_confirmation_required"):
                from .execution import free_quota_confirmed
                if not free_quota_confirmed():
                    raise QuotaExhausted(f"Confirm current free dashboards cover {demo['limits']['groq']:,} Groq tokens plus protected headroom and {demo['limits']['tavily']} Tavily credits, with paid billing off. No request sent.")
            demo.update(state="started", run_id=run_id, started_at=now())
            self.write(data)

    def finish_final_demo(self, run_id, status):
        with self.locked():
            data = self.read()
            demo = data.get("one_time_demo")
            if demo and demo.get("run_id") == run_id and demo["state"] == "started":
                demo.update(state="finished", run_status=status, finished_at=now())
                self.write(data)

    def demo_control_request(self, run_id):
        """Bound Tavily's non-credit plan checks too, including retry attempts."""
        from .execution import current_execution_phase
        if current_execution_phase() != "demo":
            return
        with self.locked():
            data = self.read()
            demo = data.get("one_time_demo")
            if not demo:
                return
            if (demo["state"] != "started" or demo.get("run_id") != run_id
                    or demo.get("control_attempts", 0) >= demo["limits"]["control_requests"]):
                raise QuotaExhausted("One-time demo control-request limit reached; no request sent.")
            demo["control_attempts"] = demo.get("control_attempts", 0) + 1
            self.write(data)

    def settle(self, ticket, actual):
        if actual is None:
            return
        with self.locked():
            data = self.read()
            for item in data["entries"]:
                if item["id"] == ticket:
                    item["actual"], item["status"] = actual, "provider_reported"
                    break
            self.write(data)

    def authorize_groq_ceiling(self, new_ceiling: int, *, repair_allowance: int = 26000,
                               demo_reserve: int = 38000, emergency_reserve: int = 7759):
        """Audited increase only, invoked by a separate explicit local CLI action.

        Existing entries are never reset, rewritten, reclassified, or refunded.
        This does not contact Groq, change provider billing, or imply remaining quota.
        """
        if new_ceiling != 110000:
            raise ValueError("Only the specifically approved cumulative 110,000-token ceiling is supported.")
        with self.locked():
            data = self.read()
            old = data["ceilings"]["groq"]
            if old > new_ceiling:
                raise ValueError("Project ceiling may not be reduced by this command.")
            if old == new_ceiling and data.get("phase_limits"):
                return {"changed": False, "old_ceiling": old, "new_ceiling": new_ceiling,
                        "phase_limits": data["phase_limits"]}
            consumed = sum(e["actual"] if e["actual"] is not None else e["reserved"]
                           for e in data["entries"] if e["provider"] == "groq")
            if old > new_ceiling or consumed + repair_allowance + demo_reserve + emergency_reserve > new_ceiling:
                raise ValueError("Approved repair, demonstration and emergency allocations exceed the ceiling; ledger unchanged.")
            if data.get("phase_limits"):
                raise ValueError("Existing phase allocations require manual review; no automatic overwrite.")
            previous_bytes = self.path.read_bytes() if self.path.exists() else None
            # Capture the complete previous ledger in a local-only backup, never the public ZIP.
            if previous_bytes is not None:
                backup = self.path.with_name("project_budget.before_110k.json")
                if not backup.exists():
                    backup.write_bytes(previous_bytes)
            data["ceilings"]["groq"] = new_ceiling
            data["phase_limits"] = {
                "repair_cumulative_cap": consumed + repair_allowance,
                "repair_allowance_at_approval": repair_allowance,
                "demo_reserve_at_approval": demo_reserve,
                "emergency_reserve": emergency_reserve,
                "baseline_consumed_or_reserved": consumed,
                "note": "Repair phase is capped at its approved envelope; demo requires explicit phase selection. No real account quota implied."
            }
            data.setdefault("ceiling_changes", []).append({"at": now(), "provider": "groq",
                "from": old, "to": new_ceiling, "approval": "explicit user approval for cumulative 110000, free tier only",
                "prior_reserved_and_reported": consumed})
            self.write(data)
            return {"changed": True, "old_ceiling": old, "new_ceiling": new_ceiling,
                    "phase_limits": data["phase_limits"]}

    def summary(self):
        with self.locked():
            data = self.read()
            result = {}
            for provider in ["groq", "tavily"]:
                entries = [e for e in data["entries"] if e["provider"] == provider]
                actual = sum(e["actual"] for e in entries if e["actual"] is not None)
                unknown = sum(e["reserved"] for e in entries if e["actual"] is None)
                result[provider] = {"actual_reported": actual, "reserved_usage_unavailable": unknown,
                                    "ceiling": min(data["ceilings"][provider], getattr(self.settings, "project_max_groq_tokens" if provider == "groq" else "project_max_tavily_credits")),
                                    "remaining_for_reservation": min(data["ceilings"][provider], getattr(self.settings, "project_max_groq_tokens" if provider == "groq" else "project_max_tavily_credits")) - actual - unknown}
                if provider == "groq" and data.get("phase_limits"):
                    caps = data["phase_limits"]
                    result[provider]["repair_remaining"] = max(0, min(result[provider]["remaining_for_reservation"], caps["repair_cumulative_cap"] - actual - unknown))
                    result[provider]["demo_reserve_at_approval"] = caps["demo_reserve_at_approval"]
                    result[provider]["emergency_reserve"] = caps["emergency_reserve"]
            return result
