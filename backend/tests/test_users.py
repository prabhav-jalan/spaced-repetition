import pytest

from app import users
from app.models import User

pytestmark = pytest.mark.db


def test_update_refuses_an_unknown_time_zone(db):
    user = User(
        google_sub="dev:x@example.com", email="x@example.com", display_name="x", timezone="UTC"
    )
    db.add(user)
    db.flush()

    with pytest.raises(ValueError, match="time zone"):
        users.update(db, user, timezone="Mars/Olympus_Mons")
    assert user.timezone == "UTC"


@pytest.mark.parametrize(
    "name",
    ["Asia/Kolkata", "Asia/Calcutta", "Asia/Kathmandu", "Asia/Katmandu", "America/New_York", "UTC"],
)
def test_iana_names_and_the_aliases_browsers_report_are_valid(name):
    assert users.is_valid_time_zone(name)
