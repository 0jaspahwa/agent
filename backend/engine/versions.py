"""Which approved policy version applies on a date (docs/data_model.md, "Which version applies")."""


def _key(policy):
    return policy.effective_from, (policy.approved_at.timestamp() if policy.approved_at else 0.0)


def version_in_force(policies, on_date):
    """The approved version with the latest effective_from on or before on_date; on equal dates the later
    approval wins. None if no version is in force yet."""
    candidates = [p for p in policies if p.effective_from <= on_date]
    return max(candidates, key=_key) if candidates else None


def latest_version(policies):
    """Used only for a line whose creation time is unreadable, so it can still be checked and reported."""
    return max(policies, key=_key) if policies else None
