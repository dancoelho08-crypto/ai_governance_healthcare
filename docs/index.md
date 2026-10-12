# AI Governance for Healthcare

**Know which AI is running in your hospital, who approved it, and whether anyone
is still watching.**

This is a system of record for hospital AI governance. Every AI tool your
organization evaluates or runs is reviewed against a published lifecycle,
approved by named people, and brought back for review when it is due.

!!! warning "Governance metadata only"

    **Governance metadata only.** Never enter patient-identifiable information,
    in any storage mode, the self-hosted server included. A governance review
    has no need for a patient's data, and the tool is not designed, configured
    or reviewed to hold it. It does hold personal data about staff; see
    [Privacy and retention](privacy.md).

[Try the demonstration :material-arrow-right:](app/index.html){ .md-button .md-button--primary }
[What adopting it takes](adopting.md){ .md-button }

## The questions you will be asked

Sooner or later a board member, an auditor, an insurer, a regulator or a
patient's lawyer asks some version of these:

1. Which AI tools are in use in our hospital today?
2. Who approved each one, when, and on what evidence?
3. Is anyone still checking that it works for our patients, or did the review
   end the day we bought it?
4. If something went wrong, what can we show?

Where there is no system of record, the answers live in committee minutes,
email threads and a spreadsheet one person keeps. They take days to assemble,
nobody can vouch for them, and they are out of date by the time they are read.

## The gap this fills

**The frameworks exist. The record does not.**

Serious frameworks for governing health AI now exist. The Coalition for Health
AI (CHAI), a US non-profit whose members include health systems, technology
vendors, academic centers and patient advocates, publishes a lifecycle with
go/no-go checkpoints. OPTICA, from Clalit Health Services in Israel, is a
77-item checklist for deciding whether to adopt a given solution. In June 2026
the WHO Regional Office for Europe named both among four complementary
approaches.

But a framework is a document. It tells a committee what to ask. It does not
remember the answers, assign the follow-up, notice that a review is overdue, or
show a board which of its tools needs attention this month.

**Approval at purchase is the start of governance, not the end.** Most hospital
technology is approved once and then mostly stays what it was. A clinical AI
model does not. How well it works depends on your patients and your data, not
only on the vendor's study. It can drift as practice and populations change. A
vendor can update it, and staff can use it for something nobody intended. OPTICA
was written because a model that performed well where it was built behaved
differently somewhere else. What a hospital needs is a review that recurs, and
a record that shows it did.

**The field has produced principles faster than practice.** A 2025 scoping
review found at least 173 published AI ethics frameworks in health care, and
only 16 studies of any of them being put into operation. None showed an effect
on patient outcomes ([the evidence, honestly](frameworks/evidence.md)). That is
the state of the discipline, and this tool does not pretend otherwise. What a
hospital can do now, and will be asked about, is show that it governed:
decisions made by named people, on recorded evidence, and revisited on a
schedule.

## What you get

**One portfolio, and an honest status for each tool.** Every AI project appears
on one dashboard with its lifecycle position, a readiness score, its next review
date and a status: *Out of compliance*, *Needs update*, *On track* or *Retired*.
The status is computed from the record by fixed rules, not typed in by whoever
is presenting. A live tool with an action past due, a criterion not met, an
overdue review or an incomplete model card is red, and the reasons are spelled
out beside it. See [How statuses are decided](compliance-rules.md).

**Decisions with names on them.** Four go/no-go checkpoints (approve design,
approve a pilot, approve deployment, review periodically) each record the
decision, the rationale and the conditions. On the shared server a sign-off
carries the name of the person signed in through your hospital's own single
sign-on, not whatever the browser claims.

**A history that cannot be quietly rewritten.** Every change is kept: who made
it, when, and what the record said afterward. The database itself refuses to
alter the audit log or the revision history, and the shipped stack runs the
service as a database role that cannot switch that protection off. A database
administrator still can, which is why the events that matter most (a project
created, deleted or purged, every read, every refusal) are also written to a
security log your IT team keeps separately. Who *read* a record is recorded too.

**Reviews that come back.** Each deployed tool has a review cadence, three
months to two years. The date is on the dashboard, and when it passes the tool
turns red.

**An applied model card and reports for everyone who asks.** Each tool gets a
model card in the structure of the CHAI Applied Model Card, with key metrics
reported against the populations they were measured on. A report for the board,
an auditor or a regulator exports as PDF, HTML or Markdown; the data exports as
JSON and CSV. See [Exports](exports.md).

**Two frameworks, one tool.** The CHAI lifecycle is always on. The OPTICA
adoption checklist can be switched on per project, and a
[crosswalk](crosswalk.md) shows where they overlap and where they do not.

**Your infrastructure, your sign-in, your data.** It runs on your own
servers or cloud account, behind the single sign-on your hospital already uses.
The dashboard and its exports contact no outside service. The data scope is
governance metadata only, and the server has retention, litigation-hold and
subject-access tools for the personal data about *staff* that a governance
record necessarily contains ([Privacy and retention](privacy.md)).

**In your staff's language.** English, Spanish, French, German, Hindi, Russian,
Simplified Chinese and Hebrew, which reads right to left.

## What it is not

- **It does not find AI tools.** It is the register, not a scanner. Someone has
  to enter each solution.
- **It does not test or monitor models.** It records that people reviewed a tool,
  on what evidence, who decided and when the next review is due. The metrics are
  entered by your team, and a Python example loads Fairlearn results into the
  model card.
- **It holds no patient data**, in any mode.
- **It is not a certification.** Reports are internal governance records, not
  legal opinions or regulatory determinations. The project is independent of
  CHAI and not endorsed by it ([Notice and license](notice.md)).
- **It has not been shown to make patients safer.** Nothing in this category has
  yet. It makes decisions legible, attributable and reviewable, and the link from
  there to clinical benefit is assumed, not demonstrated.

## What it takes

The software is free and open source (Apache License 2.0). It has one
maintainer and no vendor: there is no support contract, no response-time promise
and no hosted service. You run it, or your IT team does, as a small container
stack on a server or in your cloud account. The real costs are people's time:
an executive sponsor, a governance committee that will use it, an owner for each
AI tool, and someone in IT who can run it behind your sign-in.

[Adopting it](adopting.md) sets out the decision in full: what it takes, what it
does not do, how to try it without a commitment, and what to ask your own team
first.

## See it in action

<!-- rumdl-disable MD033 -->
<!-- A video element has no Markdown form; the rule is relaxed for this block only. -->
<video controls preload="metadata" width="100%"
       poster="assets/ai-healthcare-governance-demo.jpg"
       aria-label="A 90-second walkthrough of the CHAI governance dashboard">
  <source src="assets/ai-healthcare-governance-demo.mp4" type="video/mp4">
  Your browser cannot play this video.
  <a href="assets/ai-healthcare-governance-demo.mp4">Download the walkthrough
  (MP4, 7.5 MB)</a>.
</video>
<!-- rumdl-enable MD033 -->

A 90-second walkthrough, using sample data only. It shows the portfolio
dashboard and its statuses, opening a project and its access settings, the
stage checklists with their evidence and owners, the go/no-go checkpoints, the
applied model card preview, the OPTICA adoption review, and creating a project.

!!! note "This was recorded on the Docker stack, not the demonstration copy"

    The video shows a **shared workspace**: a server, per-project access control
    and an audit log. The demonstration copy at [`/app/`](app/index.html) runs in
    **browser-only mode**. It stores everything in your browser, has no access
    control, and keeps no server-side audit log, so it is not the same thing. See
    [Running it](running.md) for the modes.

## Where to go next

| If you are... | Start here |
|---|---|
| A CEO, board member or executive sponsor | [Adopting it](adopting.md) |
| On the AI governance committee, or the CMIO | [A review, start to finish](guide.md) |
| Evaluating the tool yourself | [Running it](running.md) |
| In IT or security | [Self-hosting](self-hosting.md), [Cloud deployment](deploy.md) and [Security claims](security-claims.md) |
| The privacy officer, DPO or records officer | [Privacy and retention](privacy.md) |
| Comparing the frameworks | [The frameworks](frameworks/index.md) and the [crosswalk](crosswalk.md) |
| A developer | [Developing it](developing.md) and [Python exports](exports.md) |
| Connecting a chatbot, or an assistant that reads the register | [The agent API](agent-api.md) and [the MCP server](mcp.md) |
