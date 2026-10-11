# A review, start to finish

This page follows one AI tool through the dashboard from the day it is
registered to the day it is retired, as a governance committee would use it. It
describes what the software does today. For the exact rule behind every status,
see [How statuses are decided](compliance-rules.md).

The steps appear in the rail on the left of every project, in this order.

## 1. Register the tool

**New project** asks only for a name. The *Project setup* page then asks for
what a committee needs to find the tool again:

| Field | What it is for |
|---|---|
| AI solution under review | The name everyone will search for |
| Health system, hospital, or department | Where it is used |
| Developer or vendor | Who built it |
| How it was sourced | Purchased from a vendor, built internally, co-developed, or an open-source model adapted locally |
| Clinical sponsor | The accountable clinical owner |
| Risk tier | Low, Moderate or High: your organization's own triage |
| Periodic review cadence once live | 3, 6, 12 or 24 months. Defaults to 6 for High risk, otherwise 12 |
| Review start date | When the review began |
| Review team | Names and roles, for example CMIO, data science, nursing informatics, compliance, patient representative |
| Scope of this review | Sites, units and versions in scope |

The same page switches the optional **OPTICA adoption review** on or off,
manages **who has access**, and holds the archive and delete controls. Changes
save as you type.

!!! note "Enter governance information only"

    Never enter patient-identifiable information. Nothing here needs it. See
    [Privacy and retention](privacy.md).

## 2. Work through the six stages

The CHAI lifecycle has six stages, and each is a checklist:

| Stage | Name | Criteria |
|---|---|---|
| 1 | Define the problem and plan | 7 |
| 2 | Design the AI system | 7 |
| 3 | Engineer the AI solution | 7 |
| 4 | Assess | 8 |
| 5 | Pilot | 6 |
| 6 | Deploy and monitor | 6 |

Each of the 41 criteria is tagged with one of CHAI's five principles: usefulness,
usability and efficacy (**U**); fairness (**F**); safety and reliability (**S**);
transparency and accountability (**T**); and security and privacy (**P**). A
criterion can be
marked **Met**, **Partial**, **Not met** or **N/A**, and carries evidence, an
owner and a due date. Give anything partial or not met an owner and a due date:
once the tool is in a pilot or live, an overdue action turns the dashboard row
red.

### Formatting notes

The **evidence or notes** field of a criterion, and a checkpoint's **rationale**,
accept a small amount of formatting, and a preview appears under the box once you
use any:

| You type | You get |
|---|---|
| `**bold**` | **bold** |
| `*italic*` or `_italic_` | *italic* |
| a line starting with `-` or `1.` | a bulleted or numbered list |
| `[the report](https://example.org/r)` | a link, with its address printed beside it |

Nothing else is formatting: raw HTML, images, tables and headings are shown as
the text they are, and a link opens only if it is an http or https address. The
text is stored exactly as you typed it (the JSON export carries it unchanged),
and the HTML, PDF and Markdown reports are written from the same reading of it.

### Evidence references

Under a criterion's notes (CHAI or OPTICA) you can add **evidence references**:
a title, a link, a date, and optionally a file. A reference points at evidence that
lives somewhere else, such as a validation report on your document system, so the
record says what was relied on without holding it.

- **A link opens only if it is an http or https address** with no user name or
  password in it. Anything else is refused when you type it, and never made a link
  when it is read back. The address is printed beside the link, so a reader sees
  where a click goes.
- **The file is never uploaded.** Pick a file and this browser computes its
  SHA-256; the record keeps the file's name, size and that digest, and nothing
  else. Later, **Check a file** tells anyone holding a copy whether it is the same
  one. Do not put patient information in a title or a file name: those are stored.
- References appear in the HTML report, the Markdown report and the JSON export
  (under each criterion's `references`), and a change to one is written to the
  change history.

The criteria are this project's own paraphrase of CHAI's, not CHAI's text. See
[Notice and license](notice.md) and the [full list](frameworks/chai-checklist.md).

**Readiness** is the share of applicable criteria that are met, where Partial
counts as half and an unanswered criterion counts as zero. It is a progress
number, not a grade, and it never decides the status by itself.

### Key metrics

Stage 4 includes a **Key metrics** table. Record each metric with its value, its
95% interval and the population it was measured on, and add one row per subgroup
for fairness results. The table feeds the model card.

CHAI publishes recommended methods and metrics for ten use cases: ambient AI,
agentic AI, clinical decision support, clinical trials, EHR information
retrieval, general health advice chatbots, mental health, discharge
summarization, prior authorization and sepsis risk prediction. Choose a use case
under **Suggested metrics from CHAI** and selecting a metric adds its name and
category. The value and the population stay blank for your team to measure,
because filling them in would be inventing results. See
[CHAI metrics](frameworks/chai-metrics.md).

## 3. Decide at the four checkpoints

Between stages sit explicit go/no-go decisions:

| Checkpoint | After stage | The decision |
|---|---|---|
| **A** | 1 | Proceed, Proceed with conditions, Revise and resubmit, or Stop |
| **B** | 4 | The same four options, to approve a pilot |
| **C** | 5 | The same four options, to approve deployment |
| **D** | 6 | Continue, Continue with changes, Retrain or revise, or Retire |

Each checkpoint page lists the criteria in the stages so far that are still
unanswered or not met, so the committee decides with the gaps in front of it.
Then it records:

- the **decision**, and who made it (a committee, or a name and role);
- the **decision date**, which you can set to the real date;
- the **rationale and conditions**: what the decision rests on, what is attached
  to it, and when it will be revisited.

The sign-off is stamped with the signed-in person and the time. On the shared
server that identity comes from your hospital's single sign-on and cannot be set
from the browser. In the browser-only demonstration nothing checks it, and the
tool says so.

A decision starting with *Proceed* or *Continue* counts as an approval, and
moves the tool to the next phase: Design, build and assess after A, Pilot after
B, Deployed after C. A **Stop** at A, B or C, or **Retire** at D, retires it.
Approving over open criteria with no rationale, or approving with conditions but
recording none, raises an amber flag on the dashboard.

## 4. Keep the applied model card

The **Applied model card** page follows the field structure of the CHAI Applied
Model Card: identity, uses and directions, warnings, trust ingredients and
resources. The panel beside it shows the card as it will read, live.

Nine fields are **core** and are marked as such: intended use and workflow,
primary intended users, targeted patient population, cautioned out-of-scope
settings, known risks and limitations, clinical risk level, outcomes and
outputs, input data source, and ongoing maintenance. A piloted or live tool with
core fields empty is flagged, and so is a card nobody has edited since the most
recent approval.

## 5. Add the OPTICA adoption review, if you want it

OPTICA asks a different question from CHAI: not "is this being run responsibly?"
but "should this organization adopt this solution?". Switched on for a project,
it adds 77 questions in 13 chapters. OPTICA's own procedure has five
stakeholders (the clinical expert, the AI solution developer, the organization's
data lead, an MLOps expert and the organization's AI lead) complete them in
seven stages; the dashboard does not show that. It groups the questions by
whether your organization, the solution's developer or either party can answer
them.

The questions are this project's paraphrase of OPTICA's. Each shows which CHAI
criterion partly covers it, or that none does, and the overview lists the
outstanding questions under those three. **OPTICA answers never change a CHAI
status**: no OPTICA item fully discharges a CHAI criterion, so evidence can be
cited in both but a judgment in one is never a judgment in the other. See the
[crosswalk](crosswalk.md).

## 6. Read the portfolio

The home page lists every AI project, with the worst first. Each row shows:

- **Lifecycle**: a small track of the six stages and four checkpoints, filled in
  as the work is done;
- **Readiness**: the percentage above;
- **Next review**: the date a deployed tool's periodic review falls due, red once
  it has passed;
- **Status**, with the reasons beneath it: *Out of compliance*, *Needs update*,
  *On track* or *Retired*.

The tiles at the top filter by status. The search box finds a project by name,
developer, sponsor or organization; **Search all text** looks in every field of
every project you can open, archived ones included, and lists where it found the
text. Archived projects leave the active portfolio and keep their record.
**Export portfolio (CSV)** writes the whole table; **Import project JSON**
brings a project in from a file (always as a new project).

## 7. Review it again, on schedule

For a deployed tool the next review date is the Checkpoint D date, or the
Checkpoint C date if there is no D yet, plus the cadence. It turns amber within
30 days of falling due and red once it has passed. When the review is done,
record a Checkpoint D decision and use **Record a new periodic review today** to
set the date forward. A D decision of *Retrain or revise* keeps an amber flag on
the tool until the next one.

## 8. Retire it

Retiring a tool (a Stop, or a D of *Retire*) takes it out of the compliance
rules: a retired tool raises no flags, and the record stays. On the server, the
retirement date also starts the retention clock. The record is kept for the life
of the tool plus six years by default, then disposed of by an operator unless a
litigation hold is on it. See [Privacy and retention](privacy.md).

## Who can do what

| Role | Can |
|---|---|
| **Owner** | Everything a writer can, plus change who has access, archive, delete, destroy history, and place or lift a litigation hold |
| **Writer** | Fill in the review: checklists, evidence, metrics, model card, checkpoints |
| **Reader** | See it, and change nothing |

On the server these are enforced by the API, not just by the buttons the page
shows. The person who creates a project is always one of its owners. A project
should have a second owner, because if its only owner leaves and their account is
disabled, nobody can open or reassign it; the access section warns the sole owner
of this. A deployment can also name emergency-access identities for exactly that
case, and every use of one is recorded in the project's own audit log
([Cloud deployment](deploy.md#offboarding-and-emergency-access)).

## The record behind it

- **Changelog.** Every change to a project, with who made it and when. It shows
  the newest 60 entries and says so, with **Show older entries** for more, up to
  500. The full history comes from the API.
- **Version history** (shared server only). Every save keeps a complete copy of
  the project. Anyone who can open the project can read its earlier revisions
  through the API.
- **Record fingerprint.** A hash of the record's contents. The setup page shows
  it, and every export carries a SHA-256 and an MD5 of the record, so you can quote
  one beside an exported report to tie it to the exact state it came from. It shows
  whether two copies are the same version. It does not prove nobody altered the
  record, and the page says so.
- **Who read what** (shared server only). Every list, read and export is recorded
  separately, for investigating an account that may have been compromised.

## Delete, destroy and archive

*Archive* hides a project and keeps it. *Delete* removes it and its live audit
log, and writes a permanent record of who deleted it and when, but **the version
history is kept**, because an audit trail that vanishes with its subject is not
one. Deleting is therefore not erasure.

For something that should never have been recorded, the delete dialog offers to
**also destroy the version history and the content of the audit log**. That is
permanent. Who changed what, and when, is kept; what was written is not. Backups
made earlier still hold it. Details are in
[Privacy and retention](privacy.md#what-can-be-erased-and-what-cannot).

## Reports and exports

The report page shows status, flags, readiness by stage, checkpoint decisions,
open gaps, the model card and the sign-off history, with the full checklist in an
appendix. It downloads as a standalone HTML file, a PDF (through your browser's
print dialog), Markdown, or the project's data as JSON. A report is written in the
reader's language and says which. Every export says which storage mode produced
it. See [Exports](exports.md).

## Language and sign-out

The language picker in the header switches between English, Spanish, French,
German, Hindi, Russian, Simplified Chinese and Hebrew. The choice is per browser,
so two people can read the same project in different languages. Where a
deployment sets it, the workspace locks after a period of inactivity and shows a
sign-out link.
