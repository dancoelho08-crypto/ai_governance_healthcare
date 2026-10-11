# OPTICA

**OPTICA** — *Organizational PerspecTIve Checklist for AI solutions
adoption* — is a checklist for deciding whether a specific AI solution is
appropriate for a specific healthcare organization. It was developed at Clalit
Health Services, a large Israeli public health organization, and published in
*NEJM AI* in 2024.

!!! info "The questions below are paraphrases"

    The OPTICA paper is **copyrighted and marked "For personal use only."** The
    checklist questions on this page are **original paraphrases** written for
    this project — they capture each item's intent but are not the paper's
    wording. They are a navigation aid, not a substitute.

    Work from the paper itself, including Table S1 in its Supplementary
    Appendix, which carries the per-item explanations the authors say the
    checklist should not be completed without. See [Notice & license](../notice.md).

## Purpose

OPTICA exists because of a specific, repeatedly observed failure: an AI model
that performed well where it was built behaves differently somewhere else.
Performance depends heavily on local data and local case mix, so approval
elsewhere — including regulatory approval — does not establish that a solution
is appropriate *here*.

The authors' argument is that existing frameworks fail organizations in one of
two ways. Either they are extended textual discussions that are hard to turn
into a concrete assessment, or they are short lists of high-level principles.
Neither takes the position of a particular organization evaluating a particular
product for a particular population.

OPTICA is deliberately the other thing: an executable checklist, written to be
completed, that asks setting-specific questions.

## Structure

77 items, in 13 chapters, grouped into 4 domains.

| Domain | Chapters | What it establishes |
|---|---|---|
| **A. Clinical need specification** | 1–2 | That a real problem exists, what performance would make a solution worth adopting, and what the alternatives are |
| **B. Data exploration** | 3–5 | Whether the development population resembles the local one, and whether every required input is actually available at the point of use |
| **C. Development & performance evaluation** | 6–9 | How the solution was built, how well it performs, whether it can be explained, and whether it is lawful and secure |
| **D. Deployment & monitoring plan** | 10–13 | How it would be rolled out, watched, evaluated, and whether it fits the organization's AI strategy |

## Procedure

This is the part that distinguishes OPTICA from a flat checklist. Items are
assigned to **five stakeholders** and completed in **seven ordered stages**
(A–G), with each stage completed by a single stakeholder.

The dashboard shows less than this. It groups outstanding items by who can
answer them (your organization, the solution's developer, or either party), a
three-valued reading of each item's stakeholder. It shows neither the five
stakeholders nor the stages, though the definition records both for every item.

| Stakeholder | Role in the process |
|---|---|
| **Clinical expert** | Leads the evaluation. Defines the need and the performance bar, then returns at later stages to judge other stakeholders' answers clinically |
| **AI solution developer** | Vendor, academic group, or internal R&D. Attests to what the organization cannot verify for itself |
| **Organizational data lead** | Knows the data resources and infrastructure; works with information security |
| **MLOps expert** | Takes the solution into production; may sit with the organization or the developer |
| **Organizational AI lead** | Reviews the completed checklist and judges fit with the organization's wider AI strategy |

Overseeing all of it is the **organizational authority** that approves medical AI
solutions — a procurement committee, an IRB, or an equivalent policy body. It
does not fill the checklist in; it receives the completed one and decides.

The ordering is not cosmetic. Items are sequenced by dependency: the clinical
expert must state the required performance threshold before anyone can judge
whether the reported performance clears it. The clinical expert reappears
throughout precisely to evaluate earlier answers — are the inputs clinically
sensible, is the development cohort close enough to ours, is this performance
good enough for the need as defined?

!!! tip "The process is designed to stop early"

    Completion can end at any stage. If the clinical expert judges the solution
    deficient on something important, or a blocking technical problem appears —
    a required input that simply is not available locally — the process halts
    there. A checklist that terminates at stage C is a finished, successful
    evaluation with a negative result, not an abandoned one.

## Status

In June 2026 the WHO Regional Office for Europe named OPTICA one of four
complementary approaches to evaluating AI in health care, alongside
[CHAI](chai.md). See [Does any of this work?](evidence.md).

The paper reports OPTICA applied to 18 AI solutions at Clalit, spanning
prediction models on structured EHR data, image analysis, operational, video,
voice, and LLM-based solutions. Reported completion time is several hours per
stakeholder, with overall duration governed by stakeholder availability.

## Source

Dagan N, Devons-Sberro S, Paz Z, et al. *Evaluation of AI Solutions in Health
Care Organizations — The OPTICA Tool.* NEJM AI 2024;1(9).
[DOI: 10.1056/AIcs2300269](https://doi.org/10.1056/AIcs2300269)
