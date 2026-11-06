"""Canonical enquiry identity for handoff views, without editing saved records."""

FIELDS = ("name", "email", "title", "company", "geography", "referral")
UNKNOWN = {"", "unknown", "not established", "not available", "unverified", "none", "n/a"}


def handoff_identity(data):
    context = data.get("buyer_context") or {}
    qualification = data.get("qualification") or {}
    lead = (qualification.get("lead") or {}) if isinstance(qualification, dict) else {}
    context = context if isinstance(context, dict) else {}
    lead = lead if isinstance(lead, dict) else {}
    result, recovered = {}, []
    for field in FIELDS:
        value = context.get(field)
        if not isinstance(value, str) or value.strip().casefold() in UNKNOWN:
            value = lead.get(field, "")
            if isinstance(value, str) and value.strip().casefold() not in UNKNOWN:
                recovered.append(field)
        result[field] = value if isinstance(value, str) else ""
    return result, recovered
