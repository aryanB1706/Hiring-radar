import pytest
from pydantic import ValidationError

from app.db.enums import LeadType
from app.schemas.lead import LeadExtraction, Urgency

MINIMAL = {"lead_type": "hiring", "confidence": 0.8, "evidence_quote": "we are hiring"}


def extract(**overrides: object) -> LeadExtraction:
    return LeadExtraction.model_validate(MINIMAL | overrides)


def test_only_type_confidence_and_quote_are_required() -> None:
    lead = extract()
    assert lead.lead_type is LeadType.HIRING
    assert (lead.role_title, lead.skills, lead.company_name) == (None, [], None)
    assert lead.urgency is Urgency.UNKNOWN


@pytest.mark.parametrize("missing", ["lead_type", "confidence", "evidence_quote"])
def test_required_fields_are_enforced(missing: str) -> None:
    data = {k: v for k, v in MINIMAL.items() if k != missing}
    with pytest.raises(ValidationError):
        LeadExtraction.model_validate(data)


@pytest.mark.parametrize(
    "bad", [{"lead_type": "admin"}, {"confidence": 1.5}, {"confidence": -0.1}, {"urgency": "now"}]
)
def test_invalid_values_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        extract(**bad)


def test_skills_are_lowercased_deduplicated_and_capped() -> None:
    lead = extract(
        skills=["Python", " python ", "FastAPI", "", "Machine  Learning"]
        + [f"s{i}" for i in range(40)]
    )
    assert lead.skills[:3] == ["python", "fastapi", "machine learning"]
    assert len(lead.skills) == 20


def test_blank_strings_become_none_and_text_is_trimmed() -> None:
    lead = extract(role_title="  ", location="  Pune ", contact_method="")
    assert (lead.role_title, lead.location, lead.contact_method) == (None, "Pune", None)


def test_currency_is_uppercased_and_oversized_values_dropped() -> None:
    assert extract(currency="inr").currency == "INR"
    assert extract(currency="indian rupees per month").currency is None


def test_swapped_budget_range_is_put_in_order() -> None:
    lead = extract(budget_min=60, budget_max=40)
    assert (lead.budget_min, lead.budget_max) == (40, 60)


def test_unknown_extra_keys_are_ignored() -> None:
    lead = extract(system_prompt="leaked", api_key="secret")
    assert not hasattr(lead, "system_prompt") and not hasattr(lead, "api_key")
