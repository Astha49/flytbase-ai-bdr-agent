"""One small inference and one search; successful checks are reused, never silently repeated."""
import json
from .models import Record
from .config import Settings, credential_status
from .workflow import new_run
from .providers.groq import GroqProvider
from .providers.tavily import TavilyProvider
from .provider import ProviderError
from .budget import ProjectBudget
from .evidence import now
from .reporting import sanitise


class ProbeResult(Record):
    ready: bool


def verify(settings):
    path = settings.run_path() / "provider_checks.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("groq", {}).get("succeeded") and data.get("tavily", {}).get("succeeded"):
            return {**data, "reused_verification": True}
    else:
        data = {"started_at": now(), "groq": {}, "tavily": {}}
    run = new_run("Provider connectivity verification only; not an assignment run.", settings)
    clients = []
    for name, factory in [("groq", GroqProvider), ("tavily", TavilyProvider)]:
        if data.get(name, {}).get("succeeded"):
            continue
        try:
            client = factory(settings, run)
            clients.append(client)
            if name == "groq":
                access = client.check_model()
                result = client.structured(ProbeResult, "Return ready=true as a JSON object. No research or other content.", {}, "probe:small Groq", max_tokens=128)
                data[name] = {"succeeded": result.ready, **access}
            else:
                plan = client.check_free_plan()
                result = client.search(["site:flytbase.com autonomous drone inspection case study"], "search:provider probe", run.as_of_date, ["flytbase.com"])
                data[name] = {"succeeded": bool(result.get("results")), "results_count": len(result.get("results", [])), "free_plan": plan}
                data["tavily_usage_after"] = client.refresh_usage()
        except ProviderError as exc:
            data[name] = {"succeeded": False, "error": str(exc)}
        data["usage"] = [*data.get("usage", []), *run.usage]
        run.usage.clear()
        data["logs"] = [*data.get("logs", []), *run.logs]
        run.logs.clear()
        data["budget"] = ProjectBudget(settings).summary()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sanitise(data), indent=2), encoding="utf-8")
    for client in clients:
        client.close()
    return data


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Small provider probes; protected live approval required.")
    parser.add_argument("--approve-live", action="store_true")
    args = parser.parse_args()
    if not args.approve_live:
        parser.error("Provider probes are locked. --approve-live is required; successful saved checks should be reused.")
    settings = Settings.from_env()
    print("Credential presence:", credential_status(), flush=True)
    from .execution import approved_live_execution
    with approved_live_execution(args.approve_live):
        data = verify(settings)
    print(json.dumps({k: v for k, v in data.items() if k not in {"logs"}}, indent=2), flush=True)
    return 0 if all(data.get(k, {}).get("succeeded") for k in ["groq", "tavily"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
