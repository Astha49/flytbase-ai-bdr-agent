"""Task-specific JSON completion reservations; these are estimates, not usage."""


def completion_target(schema, data):
    name = schema.__name__
    sources = len(data.get("sources", {}))
    if name == "Topic":
        return min(3400, 2100 + 250 * sources)
    if name == "Research":
        return 4800
    if name == "Audit":
        return min(1800, 600 + 85 * len(data.get("claims_with_paths", [])) + 35 * len(data.get("review_fields", [])))
    return {"Lead": 2400, "AccountAdvice": 1500, "MaterialChoice": 950,
            "RouteAdvice": 750, "Routing": 2300, "Responses": 4000}.get(name, 1200)
