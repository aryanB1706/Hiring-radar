import pytest

from app.classifier.prefilter import prefilter


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("hi", "too_short"),
        ("   ok thanks   ", "too_short"),
        (
            "lovely weather in the mountains this weekend, going hiking with the dog",
            "no_work_keywords",
        ),
        ("Check out our casino bonus, hiring now!!", "spam_pattern"),
        ("Join our forex signals channel for daily profits", "spam_pattern"),
    ],
)
def test_obvious_noise_is_skipped(text: str, reason: str) -> None:
    decision = prefilter(text)
    assert decision.skip is True
    assert decision.reason == reason


@pytest.mark.parametrize(
    "text",
    [
        "Acme | Senior Python Engineer | Remote (India) | apply at jobs@acme.com",
        "[HIRING] FastAPI backend dev, $40/hr",
        "Need a freelancer for a web scraper, budget 500 USD",
        "GenAI intern wanted, stipend 25k",
        "[FOR HIRE] Django developer available",  # a job seeker: the model decides, not us
        "We have a vacancy for a data person. Walk-in on Monday.",
        "Looking for someone to build an API",
    ],
)
def test_anything_that_could_be_a_lead_goes_to_the_model(text: str) -> None:
    assert prefilter(text).skip is False
