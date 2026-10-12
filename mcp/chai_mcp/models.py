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

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# What the service holds an answer's strings to. This is a SHAPE filter, a stand-in for
# the build's own list of words that this service does not have (the API has it, D-89):
#
# * an id (an item, a checkpoint, a framework) is one token of letters, digits, dots,
#   hyphens and underscores, at most 32 characters, with no space;
# * a status or a decision is one to three plain words of letters, at most 32
#   characters, so no digits, no punctuation and no sentence.
#
# Every real value of this repository's frameworks fits, with room to spare (the
# longest, "Proceed with conditions", is 23 characters). What a shape cannot do is tell
# a short phrase of plain words ("Jane Doe") from a decision: that is the API's list,
# and this is a second wall behind it, not a replacement. A custom framework whose
# words are longer, or have digits or punctuation, is refused whole until the shape is
# widened here.
ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"
ID_MAX = 32
WORD = r"^[A-Za-z]+( [A-Za-z]+){0,2}$"
WORD_MAX = 32
KEY = ID
PERSON = r"^u_[0-9a-f]{32}$"
PROJECT = r"^pr_[0-9a-f]{32}$"
TOKEN_ID = r"^[0-9a-f]{16}$"

Word = Annotated[str, Field(pattern=WORD, max_length=WORD_MAX)]


def _no_long_digit_run(value: str) -> str:
    """An id with five digits in a row is a number of somebody's (an MRN, a phone), not
    one of a framework's ids, whose longest run is two. A heuristic stand-in for the
    list of words this service does not have."""
    if DIGIT_RUN.search(value):
        raise ValueError("an id does not hold a long number")
    return value


DIGIT_RUN = re.compile(r"\d{5,}")
IdWord = Annotated[
    str, Field(pattern=ID, max_length=ID_MAX), AfterValidator(_no_long_digit_run)
]
Key = Annotated[
    str, Field(pattern=KEY, max_length=ID_MAX), AfterValidator(_no_long_digit_run)
]
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
    id: IdWord = Field(description="The item's id, a word of the framework's own.")
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
    id: IdWord = Field(
        description="The checkpoint's id, a word of the framework's own."
    )
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
