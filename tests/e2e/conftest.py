"""The end-to-end harness: a real database, a real API, and a scripted model.

`TESTING §9` and `PROGRESS §20` ask for journeys, not endpoint tests — a user
walking from signup to a scheduled task, an administrator publishing knowledge
that releases someone else's plant. Those are the paths where the seams between
phases live, and every serious defect found during this build was in a seam: a
dashboard that never decorated its tasks, a care context that silently read zero
knowledge sections, a plant list that returned other users' plants.

Three deliberate choices.

**The database is real.** Mocks confirm the shape you assumed. Every one of the
bugs above passed a green suite of unit tests before it was found by running the
thing.

**The model is not.** Four `MockProvider`s, one per agent, injected through
`app.dependency_overrides`. No journey may depend on a live LLM (`TESTING §9`):
it would be slow, billable, and — worse — non-deterministic, so a failure here
would never be trustworthy. Scripting the model is also the only way to reach the
failure paths at all.

**One app, all four agents overridden.** Even a journey about identification can
reach the Knowledge Agent (confirming a new species queues research) and the Care
Agent (publishing knowledge queues an initial plan). A journey that overrode only
the agent it was about would make a real, billable call from the second hop.
"""

from __future__ import annotations

import contextlib
import io
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agents.care.agent import CareAgent
from app.agents.care.contract import CarePlanOutput, ProposedRule, Recommendations
from app.agents.health.agent import HealthAgent
from app.agents.health.contract import HealthOutput, Observation, PossibleIssue
from app.agents.health.contract import Recommendation as HealthRecommendation
from app.agents.identification.agent import IdentificationAgent
from app.agents.identification.contract import Candidate, IdentificationOutput
from app.agents.knowledge.agent import KnowledgeAgent
from app.agents.knowledge.contract import KnowledgeContent, KnowledgeOutput, KnowledgeSection
from app.common.enums import (
    CareRuleActionType,
    HealthStatus,
    IdentificationStatus,
)
from app.infrastructure.ai.gateway import AIGateway
from app.infrastructure.ai.mock_provider import MockProvider

PASSWORD = "Journey-Passw0rd!"

# The thirteen prose sections of A16. Named here rather than imported piecemeal so
# a journey can build a complete, publishable knowledge draft in one line.
SECTION_NAMES = tuple(KnowledgeContent.model_fields)


def _load_env() -> bool:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("SUPABASE_URL"))


@pytest.fixture(scope="module")
def live_env() -> None:
    if not _load_env():
        pytest.skip("no .env with DEV credentials")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="module")
def admin_sdk(live_env):
    """The service role, used only to arrange and to inspect.

    Never to act: a journey that took a shortcut through the service role would
    skip the RLS that the real request path depends on, and would keep passing
    after a policy was removed.
    """
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@dataclass
class Script:
    """The four providers, one per agent, each scriptable from a journey."""

    identification: MockProvider = field(default_factory=MockProvider)
    knowledge: MockProvider = field(default_factory=MockProvider)
    care: MockProvider = field(default_factory=MockProvider)
    health: MockProvider = field(default_factory=MockProvider)


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def api(live_env, script: Script, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # A14's throttle is 3 AI calls a minute, which is generous for a person and
    # far too tight for a journey: a single test compresses identification,
    # research, a plan and a health check into a few seconds. Raised here rather
    # than spaced out with sleeps, because the limiter has its own tests
    # (`tests/unit/test_rate_limit.py`) and a journey that waited on it would
    # spend minutes proving something already proven.
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MINUTE", "500")
    monkeypatch.setenv("AI_RATE_LIMIT_PER_HOUR", "500")

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    from app.api.main import create_app
    from app.api.routers.care import get_care_agent
    from app.api.routers.health import get_health_agent
    from app.api.routers.identification import get_identification_agent
    from app.api.routers.knowledge import get_knowledge_agent

    app = create_app()
    app.dependency_overrides[get_identification_agent] = lambda: IdentificationAgent(
        AIGateway(script.identification, record_executions=False)
    )
    app.dependency_overrides[get_knowledge_agent] = lambda: KnowledgeAgent(
        AIGateway(script.knowledge, record_executions=False)
    )
    app.dependency_overrides[get_care_agent] = lambda: CareAgent(
        AIGateway(script.care, record_executions=False)
    )
    app.dependency_overrides[get_health_agent] = lambda: HealthAgent(
        AIGateway(script.health, record_executions=False)
    )
    # TestClient runs background tasks before returning, so a 202 has already
    # done its work by the time the journey reads the next line.
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    settings_module.get_settings.cache_clear()


@dataclass(frozen=True)
class Account:
    user_id: str
    auth: dict[str, str]
    email: str


def _with_auth_backoff(call, attempts: int = 4):
    """Retry a Supabase Auth call through a burst of rate limiting.

    Supabase applies its own rate limit to the Auth admin API, and it is shared by
    everything pointed at the project. A journey suite that creates twenty
    accounts in ninety seconds sits close enough to that ceiling that a burst can
    tip it over, and the failure surfaces as `AuthApiError: Request rate limit
    reached` in whatever test happened to be running next — which is a confusing
    way to learn about a quota.

    Backoff covers a burst. It cannot beat a sustained limit: iterating on these
    tests locally will exhaust the hour's budget, and nothing here can fix that
    except waiting. CI runs the suite once per merge to `dev`, which is well
    inside it.
    """
    import time

    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:  # the SDK's error type is not public here
            if "rate limit" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


@pytest.fixture
def account(admin_sdk) -> Iterator[Callable[..., Account]]:
    """Real accounts through real signup, so the profile trigger runs.

    Deleted afterwards, which cascades to their plants — these journeys write a
    lot of rows into a shared DEV database.
    """
    from supabase import create_client

    created: list[str] = []

    def _make(role: str = "USER") -> Account:
        email = f"e2e-{uuid.uuid4().hex[:12]}@example.com"
        user = _with_auth_backoff(
            lambda: admin_sdk.auth.admin.create_user(
                {"email": email, "password": PASSWORD, "email_confirm": True}
            )
        ).user
        created.append(user.id)
        if role == "ADMIN":
            admin_sdk.table("profiles").update({"role": "ADMIN"}).eq("id", user.id).execute()
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = _with_auth_backoff(
            lambda: anon.auth.sign_in_with_password({"email": email, "password": PASSWORD})
        ).session.access_token
        return Account(user.id, {"Authorization": f"Bearer {token}"}, email)

    yield _make

    for user_id in created:
        with contextlib.suppress(Exception):
            admin_sdk.auth.admin.delete_user(user_id)


# --- building blocks a journey reuses -------------------------------------------


def photo(colour: tuple[int, int, int] = (60, 120, 70)) -> bytes:
    """A real JPEG. The upload path decodes it with Pillow and would reject bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 800), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


def upload(api: TestClient, auth: dict, plant_id: str, context: str = "identification") -> str:
    response = api.post(
        f"/v1/plants/{plant_id}/images",
        headers=auth,
        files={"file": ("leaf.jpg", photo(), "image/jpeg"), "context_type": (None, context)},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def add_plant(api: TestClient, auth: dict) -> str:
    response = api.post("/v1/plants", headers=auth, json={})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def identified(name: str, score: float = 0.93) -> IdentificationOutput:
    return IdentificationOutput(
        status=IdentificationStatus.SUCCESS,
        candidates=[
            Candidate(scientific_name=name, common_name="צמח בדיקה", confidence_score=score)
        ],
        image_quality="תמונות ברורות ומוארות היטב.",
    )


def knowledge(text: str = "מידע מקצועי על הצמח הזה, בעברית, באורך סביר.") -> KnowledgeOutput:
    return KnowledgeOutput(
        content=KnowledgeContent(
            **{name: KnowledgeSection(text=text, confidence=0.85) for name in SECTION_NAMES}
        )
    )


WATERING = ProposedRule(action_type=CareRuleActionType.WATERING, interval_days=7)

RECOMMENDATIONS = Recommendations(
    summary="הצמח מתאים לחדר מואר ודורש השקיה מתונה לאורך השנה.",
    watering="להשקות כשהסנטימטרים העליונים של המצע יבשים.",
    light="אור עקיף בהיר, במרחק כמטר מהחלון.",
)


def care_plan(*rules: ProposedRule) -> CarePlanOutput:
    return CarePlanOutput(recommendations=RECOMMENDATIONS, rules=list(rules or (WATERING,)))


def health(
    status: HealthStatus = HealthStatus.HEALTHY, *, wants_adjustment: bool = False
) -> HealthOutput:
    return HealthOutput(
        overall_status=status,
        observations=[Observation(observation_text="שלושת העלים התחתונים מצהיבים מהקצה פנימה.")],
        possible_issues=(
            []
            if status is HealthStatus.HEALTHY
            else [
                PossibleIssue(
                    issue_name="ייתכן עודף השקיה",
                    evidence="הצהבה אחידה בעלים התחתונים ומצע לח למראה.",
                    severity=3,
                )
            ]
        ),
        recommendations=[
            HealthRecommendation(
                recommendation_text="להאריך את מרווח ההשקיה בשלושה ימים ולבדוק ניקוז.",
                requires_care_plan_adjustment=wants_adjustment,
            )
        ],
    )
