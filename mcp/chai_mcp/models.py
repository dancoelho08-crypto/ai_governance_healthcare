"""What a tool takes and returns. Typed, and checked a second time here.

The agent API builds its answers from an allowlist (server/app/agent.py). These models
are the same shape, with every string held to the pattern its field may have, and
``extra="forbid"``: a response from upstream is parsed into them, and one that does not
fit is refused, whole, instead of being passed on. So a field the API grew tomorrow, or
a name that reached a response by a bug, stops here and is never given to a model.

Nothing here is free text. An id, a status or a decision is a word of the framework's
own vocabulary; a person or a project is an opaque id or reference.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# The shape of a vocabulary word: a status, a decision, an item or checkpoint id. Up to
# four plain words of at most 48 characters. Narrower than the API's own filter
# (server/app/config.py AGENT_VALUE_SHAPE) on purpose: a sentence or an address is not a
# word, and a shape is all this service can tell. It cannot tell a name that is one word
# from a status, and does not claim to: the API's list of the build's own words does
# (D-89), and this is a second wall behind it, not a replacement.
WORD = r"^[A-Za-z0-9][A-Za-z0-9,&/+._-]*( [A-Za-z0-9,&/+._-]+){0,3}$"
WORD_MAX = 48
KEY = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
PERSON = r"^u_[0-9a-f]{32}$"
PROJECT = r"^pr_[0-9a-f]{32}$"
TOKEN_ID = r"^[0-9a-f]{16}$"

Word = Annotated[str, Field(pattern=WORD, max_length=WORD_MAX)]
Key = Annotated[str, Field(pattern=KEY, max_length=64)]
PersonId = Annotated[str, Field(pattern=PERSON)]
ProjectRef = Annotated[str, Field(pattern=PROJECT)]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Whoami(_Out):
    """Whose token this is: an opaque id, never a name."""

    user: PersonId = Field(description="The token's owner, as an opaque id.")
    token_id: Annotated[str, Field(pattern=TOKEN_ID)] = Field(
        description="This token's public id. Not the secret."
    )
    expires_at: datetime = Field(description="When this token stops working (UTC).")
    as_of: date = Field(description="Today's date in UTC, the date overdue uses.")


class Item(_Out):
    id: Word = Field(description="The item's id, a word of the framework's own.")
    status: Word | None = Field(
        description="The status as recorded by a person; null when none."
    )
    due: date | None = Field(description="The recorded due date; null when none.")
    overdue: bool = Field(
        description=(
            "A date comparison only: true when the recorded due date is before "
            "today (UTC). The status is not consulted, so a settled item with an "
            "old due date reads true. Not a verdict."
        )
    )


class Gate(_Out):
    id: Word = Field(description="The checkpoint's id, a word of the framework's own.")
    decision: Word | None = Field(
        description="The decision as recorded; null when none."
    )
    decided_on: date | None = Field(description="The recorded decision date.")
    signed_by: PersonId | None = Field(
        description="Who recorded the decision, as an opaque id, where stored."
    )
    signed_at: datetime | None = Field(
        description="When the server recorded it, where stored."
    )


class Supplement(_Out):
    framework: Key = Field(description="The supplementary framework's id.")
    enabled: bool
    items: list[Item]


class People(_Out):
    owners: list[PersonId]
    writers: list[PersonId]
    readers: list[PersonId]
    truncated: bool = Field(description="True when a list was cut at 100 ids.")


class Project(_Out):
    ref: ProjectRef = Field(description="An opaque reference to the project.")
    framework: Key | None = Field(description="The framework the record follows.")
    updated_at: datetime
    updated_by: PersonId | None = Field(description="Opaque id of the last editor.")
    people: People
    items: list[Item]
    items_truncated: bool = Field(description="True when more items were stored.")
    gates: list[Gate]
    supplements: list[Supplement]
    has_overdue: bool = Field(
        description="True when any item is overdue by the date comparison."
    )


class Portfolio(_Out):
    as_of: date = Field(description="Today's date in UTC, the date overdue uses.")
    total: int = Field(description="Projects matching the filters, before paging.")
    limit: int
    offset: int
    next_offset: int | None = Field(
        description="The offset of the next page, or null on the last."
    )
    projects: list[Project]
