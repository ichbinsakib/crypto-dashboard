"""Impact classification and surprise calculation. Pure functions, all thresholds from config."""

LEVELS = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]


def classify_impact(name, cfg):
    """-> (family, level, score). First matching rule wins; unknown events fall back to the default."""
    n = (name or "").lower()
    for r in cfg["impact"]["rules"]:
        if r["match"].lower() in n:
            return r["family"], r["level"], r["score"]
    d = cfg["impact"]["default"]
    return d["family"], d["level"], d["score"]


def surprise(actual, forecast, family, cfg):
    """-> dict(value, classification, direction, unit). Never invents a forecast: without one the
    classification is NO_FORECAST, and without an actual it is PENDING."""
    th = cfg["thresholds"].get(family) or cfg["thresholds"]["default"]
    if actual is None:
        return {"value": None, "classification": "PENDING", "direction": None, "unit": th.get("unit", "")}
    if forecast is None:
        return {"value": None, "classification": "NO_FORECAST", "direction": None, "unit": th.get("unit", "")}
    diff = round(actual - forecast, 6)
    mag = abs(diff)
    if mag < th["inline"]:
        cls = "INLINE"
    elif mag < th["moderate"]:
        cls = "MODERATE"
    else:
        cls = "LARGE"
    direction = "ABOVE" if diff > 0 else "BELOW" if diff < 0 else "INLINE"
    if cls == "INLINE":
        direction = "INLINE"
    return {"value": diff, "classification": cls, "direction": direction, "unit": th.get("unit", "")}


def revision(new_previous, old_previous):
    """Revision to an earlier reading, or None when nothing changed / nothing to compare."""
    if new_previous is None or old_previous is None:
        return None
    d = round(new_previous - old_previous, 6)
    return d if d else None
