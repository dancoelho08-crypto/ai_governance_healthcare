# Crosswalk: OPTICA and CHAI

This page reconciles the OPTICA checklist (77 items in 13 chapters, assigned
across seven completion stages A-G) against the CHAI assurance criteria (41
criteria across six lifecycle stages, s1-1 to s6-6). It is written for someone
who has to decide what a vendor dossier and an internal assurance file can and
cannot share.

Two conventions. CHAI criteria are always cited by canonical id, never by
prose; the id list used is 7/7/7/8/6/6 = 41. OPTICA items are referred to by
number and by this project's own paraphrase of what each asks; the published
checklist wording is not reproduced here.

Three relation labels are used. **Equivalent** means a completed OPTICA answer
leaves nothing of the CHAI criterion outstanding. **Partial** means the two
overlap but one asks for materially more. **OPTICA-only** means no CHAI
criterion asks for any part of it.

## 1. Headline numbers

| Relation to CHAI | Corrected | Previous pass |
| ---------------- | --------: | ------------: |
| Equivalent       |         0 |             3 |
| Partial          |        61 |            60 |
| OPTICA-only      |        16 |            14 |
| **Total items**  |    **77** |        **77** |

**There are no equivalences left.** The previous pass claimed three (1.1 to
s1-1, 9.3 to s4-7, 12.1 to s1-3) and all three fail on their own evidence.
s1-3 reads only "Success measures and a baseline to compare against are
defined"; OPTICA 12.1 additionally requires deployment success criteria to be
measurable and to be kept distinct from the model's accuracy metrics, neither
of which s1-3 carries. s4-7 reads "Security review or vendor security
assessment completed", an activity; OPTICA 9.3 asks for a verdict that the
solution meets the institution's requirements, with remediation status
attached. A completed review with open findings satisfies s4-7 and fails 9.3.
s1-1 pairs a problem statement with a target outcome agreed across clinical
*and operational* stakeholders; OPTICA 1.1 is one clinical expert's answer and
its affected-population element sits in s1-4 while its care-setting element
sits in s2-2, a stage later.

This matters more than the arithmetic suggests. The headline "OPTICA and CHAI
fully coincide somewhere" was resting on three mappings, and none survives
scrutiny. The closest surviving pair is 9.3 to s4-7: same party, same point in
the lifecycle, same artifact class, with only the conformity verdict
outstanding. Treat that pair as the ceiling of what cross-recognition can look
like, not the floor.

**Coverage of CHAI.** 36 of 41 criteria are cited somewhere in the corrected
crosswalk (87.8%), up from 35 (85.4%). The gain is s3-7, which OPTICA 11.3 and
11.6 demand almost verbatim ("who owns the alerts", "who reviews results")
while the previous pass recorded it as an uncovered gap. Five criteria are
never cited: **s1-5, s3-5, s4-8, s5-4, s6-5**.

Citation counts flatter OPTICA, so this page also reports an effective figure.
A criterion is **reached** when a complete OPTICA dossier yields evidence a
reviewer could accept against it; **touched** when OPTICA produces only a
fragment or an adjacent artifact; **absent** when nothing in OPTICA produces
anything against it.

| CHAI stage                 | n  | Cited | Reached | Touched | Absent |
| -------------------------- | -: | ----: | ------: | ------: | -----: |
| s1 Define the problem/plan |  7 |     6 |       5 |       1 |      1 |
| s2 Design the AI system    |  7 |     7 |       4 |       2 |      1 |
| s3 Engineer the solution   |  7 |     6 |       6 |       0 |      1 |
| s4 Assess                  |  8 |     7 |       5 |       0 |      3 |
| s5 Pilot                   |  6 |     5 |       2 |       3 |      1 |
| s6 Deploy and monitor      |  6 |     5 |       3 |       3 |      0 |
| **Total**                  | 41 |    36 |  **25** |   **9** |  **7** |

**25 of 41, not 36 of 41, is the number to plan with.** Three criteria are
cited yet absent, which is the single most misleading artifact in the previous
pass: s4-4 (silent or shadow evaluation in the live environment), s4-5
(installation qualification) and s2-6 (safety reporting pathway naming who
reports to whom) appear in the crosswalk only inside rationales explaining
that OPTICA does *not* ask for them. Searching all 77 OPTICA items returns no
hit for shadow, silent, install, safety, incident, rollback, retire or stop
rule. Conversely s6-5 is never cited but is partly touched, because OPTICA 9.3
does cover access control design and vulnerability remediation, just once and
never on a schedule.

The correction that matters most for the narrative is at Stage 4. The previous
pass read 7/8 there and concluded that OPTICA is densest where CHAI assesses
and thinnest where CHAI engineers. Effective coverage inverts that: Stage 4 is
5/8 and Stage 3 is 6/7. OPTICA's strongest alignment with CHAI is at the
engineering stage, where it interrogates the development data and the
developer's process far harder than CHAI does; its weakest is at pilot (2/6).

**Corrections applied.** Nine relation relabels (1.1, 9.3, 12.1 down from
equivalent to partial; 3.2, 6.3, 7.5, 8.1 down from partial to OPTICA-only;
5.3 and 7.4 up from OPTICA-only to partial), plus 7.1 retained as partial on a
narrower anchor. Ten citation fixes (+s1-4 at 1.1, +s5-3 at 1.6, +s3-2 at
3.6, +s2-1 at 4.3, -s5-1 at 7.12, +s2-7 at 10.7, +s3-7 at 11.3 and 11.6,
+s1-3 and +s6-6 at 12.2). Seven misquotes repaired, the consequential ones
being s4-2 (which names no party and no dataset; "on local data" had been
imported from s4-1), s1-3 (which defines measures and a comparator, not
thresholds) and s3-2 (whose scope is demographic and socio-demographic make-up
only). Two producer reassignments (1.4 and 11.6 from either to adopter).

**Corrections rejected, with reasons.** Three.

*7.2 to OPTICA-only: rejected.* The argument was that s4-2 belongs to the
adopting organization working on local data, so a vendor's subgroup tables
cannot touch it. But the same correction set establishes that this party-and-
dataset wording is not in s4-2 at all. With the misquote removed, a
developer-published stratified table can in principle discharge s4-2, so the
overlap is real. 7.2 stays partial; the residue is the strata CHAI does not
name (comorbidity burden, care site) and the fact that CHAI nowhere requires
the disclosure to arrive before the adopter decides whether a local assessment
is worth mounting.

*7.1 to OPTICA-only: rejected in part.* s4-1 is dropped, because it binds the
dataset to local data representative of the deployment population and no
vendor evidence can satisfy that. s4-3 is kept, because "Calibration checked,
not only discrimination" binds neither party nor dataset, and OPTICA 7.1
explicitly requires calibration among the metrics matched to the output type.
7.1 therefore remains partial on s4-3 alone. The rule this establishes is used
throughout: **where a CHAI criterion binds the party or the dataset, vendor
evidence cannot discharge it; where it does not, vendor evidence can.** That
rule is also why 7.5 does become OPTICA-only, since its only anchor was s4-1.

*s3-7 at 11.4: rejected.* OPTICA 11.4 names tracked statistics, a review
cadence and escalation triggers, but designates nobody, so there is nothing
for a criterion about designating responsible people to attach to. s3-7 is
carried by 11.3 and 11.6 only.

**One extension beyond the supplied corrections.** OPTICA 11.3 and 11.4 are
moved from adopter to role-dual. The source defines the MLOps expert as a role
that, depending on the deployment strategy, sits either with the organization
or with the developer; the previous pass applied that to 10.5-10.7 but not to
11.3-11.4, which are the same role at the same completion stage. With this fix
the producer column becomes a pure function of OPTICA's own stakeholder
assignment rather than a judgment of ours, which is worth more than the two
items it moves. A second, smaller extension: s2-7 is added to 9.3, since once
9.3 is no longer an equivalence there is no reason to exclude the data-flow
review and access-control design that OPTICA 9.3 explicitly demands.

## 2. Chapter by chapter

Coverage is graded on how much of the chapter's substance CHAI demands
anywhere: **Moderate** (CHAI asks for most of the subject, in weaker form),
**Limited** (CHAI touches the subject but asks for something materially
different), **Minimal** (one thin anchor or none).

| #  | OPTICA chapter       | n  | CHAI stages    | Crit | None | Coverage |
| -- | -------------------- | -: | -------------- | ---: | ---: | -------- |
| 1  | Clinical need        |  6 | s1; s2 s5 s6   |   10 |    0 | Moderate |
| 2  | Alternatives         |  3 | s1             |    1 |    2 | Minimal  |
| 3  | Population           |  6 | s3; s1 s2 s4   |    5 |    2 | Limited  |
| 4  | Input data           | 10 | s3; s1 s2 s4 s6|    9 |    2 | Limited  |
| 5  | Output data          |  6 | s2; s1 s3 s4   |    7 |    0 | Limited  |
| 6  | Development process  |  6 | s1 s2 s3 s4    |    4 |    4 | Minimal  |
| 7  | Performance          | 12 | s4; s1 s3 s5   |   10 |    3 | Limited  |
| 8  | Explainability       |  3 | s4             |    1 |    1 | Minimal  |
| 9  | Regulatory/security  |  4 | s1; s2 s3 s4 s5|    5 |    0 | Moderate |
| 10 | Deployment plan      |  7 | s2; s1 s3 s4 s5|    9 |    0 | Limited  |
| 11 | Monitoring plan      |  6 | s6; s3         |    5 |    0 | Moderate |
| 12 | Evaluation plan      |  5 | s5; s1 s2 s6   |    8 |    0 | Moderate |
| 13 | Strategy fit         |  3 | s1             |    2 |    2 | Minimal  |

"Crit" counts the distinct CHAI criteria the chapter touches; "None" counts
the chapter's items with no CHAI anchor at all.

Four patterns are worth a governance officer's attention.

**Chapter 11 (monitoring) is the only chapter where CHAI sometimes asks more
than OPTICA.** Its six items land almost entirely in CHAI Stage 6, and s6-2
(ongoing subgroup performance monitoring) has no OPTICA counterpart: OPTICA
11.6 plans ongoing accuracy measurement without ever requiring it to be
stratified. If you are working from an OPTICA dossier, this is the one chapter
where CHAI will add requirements rather than absorb yours.

**Chapters 2, 6, 8 and 13 are where OPTICA is effectively alone.** Nine of
OPTICA's 16 unanchored items sit in these four chapters: how you chose between
candidates, how the model was actually built, whether global attribution
exists, and whether this purchase fits the organization's AI portfolio. The
other seven are scattered through chapters 3, 4 and 7.

**Chapter 7 (performance) is the most structurally awkward.** Twelve items,
six answerable only by the vendor and six only by the adopter, spanning four
completion stages and ten CHAI criteria across four CHAI stages. It is also
where the clock conflict in section 5 does the most damage.

**Chapters 3, 4 and 5 touch CHAI widely but shallowly.** They cite five, nine
and seven distinct criteria respectively (chapter 5's seven counts the one
criterion 5.3 reaches, which section 7 explains is not yet recorded), yet almost
every mapping carries substantial residue, because CHAI documents data at
dataset level while OPTICA works per cohort rule, per variable and per label.

## 3. Where each framework is alone

**What OPTICA asks that CHAI never does** (16 items, grouped):

*Choosing between candidates* (2.2, 2.3, 7.8). A scored head-to-head of the
shortlist against pre-set thresholds with every number attributed to its
source; a reasoned selection with the trade-offs visible; a sanity check of
the chosen product's claims against the alternatives. CHAI's s1-2 asks whether
AI is an appropriate intervention, which is a question about the class of
intervention, not about which product to buy. Nothing in CHAI's 41 criteria
mentions cost, cost of ownership or a competing offering.

*How the model was built* (3.4, 6.1, 6.2, 6.3, 6.4, 8.1). Partition design and
whether patients leak across splits; the algorithm, objective, tuning and
training regime; the argument that the method suits the output type; how
censoring and loss to follow-up were handled when labels were formed; target
leakage controls and the results of testing for them; global feature
importance with the attribution method named. CHAI's engineering stage is
about data and process hygiene (s3-1, s3-4, s3-5) and never reaches
methodology. Note the asymmetry at splits: OPTICA 3.4 asks for split integrity
that CHAI never requires, while CHAI's s3-5 asks for the version control that
would make OPTICA's answer auditable, which OPTICA never requires.

*Technical specification of the product* (3.2, 4.2). The development cohort's
patient count, and an input specification covering formats, units, coding
systems, resolution and mandatory preprocessing. CHAI's s3-2 is scoped to
demographic and socio-demographic make-up, which is composition, not scale;
the model card touches size and data type in passing, but a card prompt is not
a criterion.

*The vendor's evidence base, including the negative* (7.5, 7.6). Whether
validation outside the training setting has ever been performed, where and
with what results - or an explicit statement that it has not; and how the
product has behaved in production elsewhere, with provenance - or an explicit
statement that it has never been fielded. CHAI's production and real-world
performance criteria (s6-1, s6-2, s5-3) are all discharged by the adopting
organization on its own deployment. The explicit negative, which is the single
most decision-relevant disclosure a buyer can receive, has no CHAI home.

*Clinical sufficiency and organizational fit* (4.6, 13.1, 13.3). A clinician's
audit of whether the model is fed what the task clinically requires; a verdict
on the credibility of the dossier itself; and an assessment of portfolio
overlap, vendor concentration, reusability and precedent. CHAI scopes every
criterion to the single solution under review and has no slot for a judgment
about the quality of the answers given to the others.

**What CHAI asks that OPTICA never does.** Seven criteria are absent outright
and nine more are touched only in fragments.

| CHAI id | Track | What is missing in OPTICA                      |
| ------- | ----- | ---------------------------------------------- |
| s1-5    | S     | Harm and failure-mode register, with severity  |
|         |       | and likelihood, before commitment              |
| s2-6    | T     | Safety-incident reporting pathway, naming who  |
|         |       | reports to whom                                |
| s3-5    | T     | Version control over datasets, code and model  |
|         |       | artifacts                                      |
| s4-4    | S     | Silent or shadow evaluation in the live        |
|         |       | environment                                    |
| s4-5    | S     | Installation qualification                     |
| s4-8    | T     | Safety pathway revised with what assessment    |
|         |       | revealed                                       |
| s5-4    | F     | Pilot results checked across patient groups    |

| CHAI id | Track | What OPTICA supplies, and what it leaves out    |
| ------- | ----- | ----------------------------------------------- |
| s1-6    | T     | Clinical accountability for a result (10.3) and |
|         |       | a receiving governance body (12.5); no          |
|         |       | program owner, no decision rights             |
| s2-3    | F     | Subgroup adequacy in development data (3.5) and |
|         |       | vendor strata (7.2); no pre-specified fairness  |
|         |       | criteria for the adopter's own evaluation       |
| s2-4    | S     | Thresholds everywhere, but as adoption          |
|         |       | acceptance bars (1.5, 7.7); the model's         |
|         |       | operating point is never defined or justified   |
| s5-1    | U     | Site-by-site phasing (12.3); no pilot duration, |
|         |       | no stop rules                                   |
| s5-5    | S     | Adverse consequences as a measurement target    |
|         |       | (12.2); no near-miss register, no review        |
| s5-6    | T     | Patient disclosure (9.2); user training is      |
|         |       | absent from all 77 items                        |
| s6-2    | F     | Ongoing accuracy measurement (11.6), never      |
|         |       | stratified by patient group                     |
| s6-4    | S     | Escalation triggers on output drift (11.4); no  |
|         |       | incident response, rollback or retirement       |
| s6-5    | P     | Access control design and vulnerability         |
|         |       | remediation at one point in time (9.3); no      |
|         |       | recurring access review or patch cadence        |

The pattern is clean and it is not a defect in either instrument. Of the seven
absent criteria, three are CHAI's safety track, three its trust and
accountability track, one its fairness track. **None is from the usefulness
track and none from the privacy and security track** - OPTICA reaches every
CHAI criterion in both of those, at least in part. What it misses is
registers, schedules, standing roles and feedback loops.

That follows from what each instrument is. OPTICA is a pre-adoption appraisal
dossier: a structured interrogation of one candidate product and its fit to
one organization, authored by a relay of named roles and settled by a go/no-go
decision. Everything in it is a fact about the product, a property of the
local setting, or a judgment a named person records. A register of harms you
have not yet seen, a pathway for incidents that have not yet happened, a
schedule for reviews that recur after launch - none of these is a fact a buyer
can read out of a submission, so an instrument built to appraise a submission
has nowhere to put them.

CHAI is the mirror image. It is a lifecycle assurance program, and its
criteria are written as states the organization must be in at each stage. That
is exactly why it carries the standing obligations OPTICA cannot, and exactly
why it does not interrogate the product: it assumes a solution exists and
governs its life, where OPTICA assumes nothing and has to decide whether the
solution deserves one. Neither omission is an error. The two instruments are
answering different questions, and the gaps fall where you would predict.

## 4. The producer split

This is the practical obstacle to answering once, and it is larger than the
coverage numbers suggest.

| Who can answer                | Items | Share |
| ----------------------------- | ----: | ----: |
| Only the vendor (developer)   |    29 |   38% |
| Only the adopting organization|    43 |   56% |
| Either, depending on hosting  |     5 |    6% |

These are not our judgment. They are OPTICA's own stakeholder column: all 29
items at completion stage B are assigned to the AI solution developer, the
five MLOps-expert items (10.5-10.7, 11.3, 11.4) are assigned to a role the
source explicitly defines as sitting with the organization or the developer
depending on deployment strategy, and the remaining 43 are assigned to the
clinical expert, the organizational data lead or the organizational AI lead.

Three consequences for a shared-answer strategy.

**Ten of the 29 vendor items have no CHAI anchor at all** (3.2, 3.4, 4.2, 6.1,
6.2, 6.3, 6.4, 7.5, 7.6, 8.1). A vendor that has conscientiously completed a
CHAI program has had no reason to prepare any of them. These are the
cohort count, the split design, the input specification, four of the six
development-process questions, the two evidence-base disclosures and global
feature importance. If your procurement depends on them, they must be written
into the contract; no assurance credential will have produced them.

**Three CHAI criteria are reachable, in this crosswalk, only through items the
vendor alone can answer**: s2-3 (via 3.5), s3-3 (via 6.5) and s4-2 (via 6.5
and 7.2). Twenty-three are reachable only through items on the adopting side,
including the role-dual MLOps ones, and ten through both. So the dependency
runs in both directions, but asymmetrically: a vendor cannot hand you a CHAI
file, and you cannot assemble one without the vendor.

**Of the seven chapters the vendor answers in, only chapter 6 can be completed
by one party.** Chapter 4 splits five-five between vendor and adopter, chapter
5 three-three, chapter 7 six-six, chapter 3 five-one, chapter 8 two-one and
chapter 11 two-two-two across vendor, dual and adopter. The
natural unit of exchange is therefore not a chapter and not a domain but the
individual item, which is precisely the granularity at which cross-framework
reuse is most expensive to administer.

## 5. The three structural conflicts

**The gating conflict: CHAI checkpoints against an OPTICA stakeholder relay.**
CHAI's six stages are a lifecycle. Each is a checkpoint over the whole
program, and the question at each gate is whether that stage's criteria are
met. OPTICA's seven completion stages are not a lifecycle at all; they are a
relay that orders *who answers next* - clinical expert (9 items), developer
(29), clinical review (12), organizational data lead (7), MLOps expert (5),
clinical expert again (12), organizational AI lead (3). The two orderings do
not commute. CHAI places success measures and a baseline at Stage 1, before a
solution exists; OPTICA's deployment success criteria (12.1) are written at
stage F, after the developer pass, the clinical review, the data-lead pass and
the MLOps pass. CHAI places monitoring ownership at Stage 3 (s3-7); OPTICA
produces it at stages E and F. CHAI places retraining cadence and change
control at Stage 6 (s6-3); OPTICA asks the developer for it at stage B. The
most-cited criterion of all, s1-3, is anchored by seven OPTICA items spread
across stages A, C, D and F.

The practical consequence is that no single completion percentage can be
computed from the other framework's file. An OPTICA dossier can be 100%
complete while CHAI Stage 1 is still open, because nothing in OPTICA produces
a harm register (s1-5) or names a program owner and decision rights (s1-6).
A CHAI Stage 4 sign-off can be complete while most of OPTICA stage B is
unanswered. Mapping the items does not map the gates, and a governance process
that reports "we are through CHAI Stage 4, therefore OPTICA chapter 7 is
done" will be wrong in both directions.

**The clock conflict: the developer's past against the adopter's future.**
OPTICA's performance chapter opens with six vendor items (7.1-7.6) that ask
for evidence which already exists: retrospective figures with uncertainty
intervals, stratified tables, the evaluation cohort's composition, the
sampling design and true event rate, prior external validation, in-production
behavior elsewhere. CHAI's assess-stage criteria ask for evidence that does
not yet exist and must be generated locally: s4-1 requires performance
validated on local data representative of the deployment population.

These are not substitutes in either direction. A complete vendor evidence
package discharges none of s4-1, because s4-1 binds the dataset. A completed
s4-1 validation tells a reader nothing about whether the product was ever
validated anywhere else (7.5) or how it has behaved in production (7.6), and
it cannot be run before the purchase decision those items exist to inform.
The dividing rule is textual and worth applying item by item: where a CHAI
criterion binds the party or the dataset, vendor evidence cannot discharge it;
where it does not, it can. s4-1 binds, so 7.5 is left with no anchor at all.
s4-2 (subgroup comparison), s4-3 (calibration), s4-6 (explanations suited to
users) and s4-7 (security review) bind neither, so vendor evidence genuinely
counts toward them - which is why 7.1, 7.2 and 6.5 keep their mappings.

Note also what sits in the gap and belongs to neither clock: OPTICA 7.9 asks
whether a local evaluation is even feasible with the data on hand and what it
would cost, and 7.10 asks whether retrospectively extracted inputs match what
the live system would receive. CHAI has nothing comparable. s4-1 simply
presumes that usable local data exist, which is the assumption that most often
fails in practice.

**The decline conflict: a reasoned "we chose not to" against an unconditional
obligation.** At least five OPTICA items accept a documented negative as a
complete answer: 1.6 (quantify the expected benefit, or record why it cannot
be quantified), 7.11 (the local evaluation's results and a clinical verdict,
or a documented reason it was not undertaken), 8.1 (global feature importance,
or a technical justification that it is infeasible for this model class), 10.3
(the human-in-the-loop arrangement, or a reasoned case for operating without
one) and 12.3 (an evaluable rollout design, or a documented reason none is
feasible). OPTICA 7.12 is conditional in the same way - it asks what a pilot
revealed only where a pilot was judged worthwhile - and 2.1 instructs that an
empty market scan be recorded as a deliberate finding.

CHAI's corresponding criteria are unconditional. s4-1 says performance is
validated on local data, full stop. The Stage 5 criteria presume a pilot
happens. s2-5 presumes an oversight path exists. The only conditionals in the
41 are s4-5 ("where applicable") and s3-6 ("where appropriate"), neither of
which is a decline branch.

The consequence runs both ways and is easy to miss. A dossier that is complete
under OPTICA can be non-conformant under CHAI purely because it exercised a
decline branch - an organization that reasonably concluded a local
retrospective evaluation was infeasible has answered 7.11 and failed s4-1. And
moving the other way, CHAI has nowhere to record *why* something was not done,
so the decline rationale - usually the most governance-relevant sentence in
the whole file - is simply lost in translation.

## 6. Verdict on simultaneous completion

**Simultaneous completion is not achievable, and should not be promised.**
With zero equivalences across 77 items, there is no pair of questions where
filing one answer closes both. What is achievable is substantial reuse of
underlying evidence, with the CHAI side generally being the lighter ask, plus
a defined remainder that must be produced by hand.

**Genuinely shareable: 25 of CHAI's 41 criteria.** A complete OPTICA dossier
produces evidence a reviewer could accept against s1-1, s1-2, s1-3, s1-4,
s1-7; s2-1, s2-2, s2-5, s2-7; s3-1, s3-2, s3-3, s3-4, s3-6, s3-7; s4-1, s4-2,
s4-3, s4-6, s4-7; s5-2, s5-3; and s6-1, s6-3, s6-6. In most of these the
OPTICA answer is the larger artifact, so the direction of reuse is OPTICA to
CHAI, not the reverse. Two carry caveats that should be written into any reuse
policy: s4-1 is only discharged where OPTICA 7.11's local evaluation was
actually performed rather than declined, and s1-3's baseline element needs
OPTICA 1.2's status-quo figures explicitly attached, since 1.5 and 12.1 supply
measures without a comparator.

**Not shareable: 16 of 41.** Seven absent (s1-5, s2-6, s3-5, s4-4, s4-5, s4-8,
s5-4) and nine where OPTICA yields only a fragment (s1-6, s2-3, s2-4, s5-1,
s5-5, s5-6, s6-2, s6-4, s6-5). Watch the three that are cited in the crosswalk
but produce nothing - s2-6, s4-4 and s4-5 - because an automated mapping will
report them as covered.

**What a user must still do by hand**, in rough order of how often it bites:

1. Write a prospective harm and failure-mode register with severity and
   likelihood, before commitment (s1-5). No OPTICA item asks for one; 1.2
   looks backwards at the status quo's harms and 12.2 measures harm after
   go-live.
2. Draft a safety-incident reporting pathway naming who reports to whom, and
   revise it with what assessment revealed (s2-6, s4-8). OPTICA 12.5's
   reporting plan is an effectiveness channel to a governance body, not a
   safety channel.
3. Name the accountable program owner, the governance body and the decision
   rights (s1-6), which OPTICA distributes across 10.3, 12.5 and 13.1 without
   ever consolidating.
4. Stratify results by patient group after adoption: pilot results (s5-4) and
   ongoing monitoring (s6-2). All of OPTICA's equity work (3.5, 6.5, 7.2) sits
   before the purchase decision and most of it on the vendor's side.
5. Define and clinically justify the model's operating threshold (s2-4), and
   pre-specify the subgroups and fairness criteria your own evaluation will
   use (s2-3). OPTICA's thresholds are adoption bars, not operating points.
6. Put datasets, code and model artifacts under version control (s3-5).
7. Run, or document a waiver of, a silent evaluation (s4-4) and installation
   qualification (s4-5).
8. Fix pilot duration and stop rules (s5-1), stand up adverse-event and
   near-miss tracking (s5-5), train users (s5-6), and document incident
   response, rollback and retirement criteria (s6-4).
9. Convert OPTICA 9.3's one-off security verdict into a recurring access
   review and patch cadence (s6-5).
10. Commission the local validation itself (s4-1) wherever OPTICA 7.11's
    decline branch was used.

**And in the other direction**, for an organization that already runs CHAI and
is adopting OPTICA: expect to obtain 29 answers from the vendor, of which ten
correspond to nothing CHAI ever asked for, and to write 16 OPTICA items that
have no CHAI source at all - the procurement comparison, the model's
construction, the vendor's evidence base including its negatives, and the
portfolio judgment. Those 16 are the reason to run OPTICA, not an overhead on
top of CHAI.

## 7. Item by item

Each OPTICA item's relation to CHAI and the CHAI criteria it cites, exactly as
OPTICA's framework definition records them. This is the data the dashboard's
"covered by CHAI" chips and the [OPTICA checklist](frameworks/optica-checklist.md)
are drawn from. Where an item cites more than one criterion, the first listed
is the one its chip shows. The table is written from the definition by
`scripts/gen_crosswalk.py`, and `pixi run check-crosswalk` fails if the table
disagrees with the definition, or if most counts, lists and corrections this
page states about the current mapping do (#174). A few sentences are found by a
looser search and may be reworded without the check noticing. That covers
the relations, the criteria cited and who answers each item, and how they add
up by CHAI stage, by chapter and by completion stage. It does not cover what
cannot be derived from the definition: the previous pass's figures (checked by
`tests/test_crosswalk.py` against a record of that pass), the coverage grades,
the history of the audit, and the reviewer's grading of each criterion as
reached, touched or absent, which is checked only for agreeing with itself
and with what is cited.

Two items are not yet recorded there: 5.3 and 7.4 are partial on this page, but
this page does not name the CHAI criteria they reach, so the definition still
marks them OPTICA-only and the dashboard shows them as not covered by CHAI.
Which criteria they cite is an open question for the owner (R-69 in
REQUIREMENTS.md, #174).

<!-- Generated from app/frameworks/optica/framework.json by scripts/gen_crosswalk.py (pixi run gen-crosswalk). Do not edit by hand. -->

| Item | Who answers | Relation to CHAI | CHAI criteria |
| ---- | ----------- | ---------------- | ------------- |
| 1.1 | adopter | partial | s1-1, s1-4 |
| 1.2 | adopter | partial | s1-2, s1-3 |
| 1.3 | adopter | partial | s2-1, s2-2, s2-5 |
| 1.4 | adopter | partial | s2-2 |
| 1.5 | adopter | partial | s1-3, s2-4 |
| 1.6 | adopter | partial | s1-3, s6-6, s5-3 |
| 2.1 | adopter | partial | s1-2 |
| 2.2 | adopter | OPTICA-only | — |
| 2.3 | adopter | OPTICA-only | — |
| 3.1 | developer | partial | s3-1 |
| 3.2 | developer | OPTICA-only | — |
| 3.3 | developer | partial | s3-2 |
| 3.4 | developer | OPTICA-only | — |
| 3.5 | developer | partial | s3-2, s2-3 |
| 3.6 | adopter | partial | s4-1, s1-4, s3-2 |
| 4.1 | developer | partial | s3-1 |
| 4.2 | developer | OPTICA-only | — |
| 4.3 | developer | partial | s2-2, s2-1 |
| 4.4 | developer | partial | s3-4 |
| 4.5 | developer | partial | s3-4 |
| 4.6 | adopter | OPTICA-only | — |
| 4.7 | adopter | partial | s1-7, s4-1 |
| 4.8 | adopter | partial | s2-7, s4-4 |
| 4.9 | adopter | partial | s4-1, s6-1 |
| 4.10 | adopter | partial | s3-1 |
| 5.1 | developer | partial | s2-4 |
| 5.2 | developer | partial | s3-1 |
| 5.3 | developer | OPTICA-only | — |
| 5.4 | adopter | partial | s1-1 |
| 5.5 | adopter | partial | s4-1, s1-3 |
| 5.6 | adopter | partial | s4-3, s2-4 |
| 6.1 | developer | OPTICA-only | — |
| 6.2 | developer | OPTICA-only | — |
| 6.3 | developer | OPTICA-only | — |
| 6.4 | developer | OPTICA-only | — |
| 6.5 | developer | partial | s3-3, s4-2 |
| 6.6 | developer | partial | s2-1, s1-1 |
| 7.1 | developer | partial | s4-3 |
| 7.2 | developer | partial | s4-2 |
| 7.3 | developer | partial | s3-1, s3-2 |
| 7.4 | developer | OPTICA-only | — |
| 7.5 | developer | OPTICA-only | — |
| 7.6 | developer | OPTICA-only | — |
| 7.7 | adopter | partial | s1-3 |
| 7.8 | adopter | OPTICA-only | — |
| 7.9 | adopter | partial | s1-7, s4-1 |
| 7.10 | adopter | partial | s4-4 |
| 7.11 | adopter | partial | s4-1 |
| 7.12 | adopter | partial | s5-2, s5-3 |
| 8.1 | developer | OPTICA-only | — |
| 8.2 | developer | partial | s4-6 |
| 8.3 | adopter | partial | s4-6 |
| 9.1 | adopter | partial | s1-7 |
| 9.2 | adopter | partial | s5-6, s1-7 |
| 9.3 | adopter | partial | s4-7, s2-7 |
| 9.4 | adopter | partial | s1-7, s3-6 |
| 10.1 | adopter | partial | s2-2, s2-1 |
| 10.2 | adopter | partial | s2-1, s5-2 |
| 10.3 | adopter | partial | s2-5, s1-6 |
| 10.4 | adopter | partial | s4-6 |
| 10.5 | either | partial | s2-7, s4-5 |
| 10.6 | either | partial | s4-5 |
| 10.7 | either | partial | s3-4, s2-7 |
| 11.1 | developer | partial | s6-3 |
| 11.2 | developer | partial | s6-3 |
| 11.3 | either | partial | s6-1, s3-7 |
| 11.4 | either | partial | s6-1, s6-4 |
| 11.5 | adopter | partial | s6-3 |
| 11.6 | adopter | partial | s6-1, s6-2, s3-7 |
| 12.1 | adopter | partial | s1-3 |
| 12.2 | adopter | partial | s5-3, s5-5, s1-3, s6-6 |
| 12.3 | adopter | partial | s5-1 |
| 12.4 | adopter | partial | s5-2, s6-6 |
| 12.5 | adopter | partial | s6-3, s2-6 |
| 13.1 | adopter | OPTICA-only | — |
| 13.2 | adopter | partial | s1-2, s1-6 |
| 13.3 | adopter | OPTICA-only | — |

<!-- End of the generated table. -->

## How this page was produced

The crosswalk was built by mapping each of the 77 OPTICA items onto canonical
CHAI criterion ids, then auditing every mapping through three adversarial
passes: one hunting over-claimed equivalences, one hunting missed coverage, and
one checking that cited ids say what the mapping claims they say. The audit
produced 34 corrections and 8 hard errors — cases where a mapping cited a CHAI
criterion that does not say what was attributed to it.

An earlier pass of this analysis ran on a corrupted input, in which CHAI stages
4 and 5 had been merged by a parsing bug. Its figures (8 equivalences, 27
uncovered CHAI criteria) were wrong in both directions and are not used here.

The underlying data is committed as OPTICA's framework definition,
[`app/frameworks/optica/framework.json`](https://github.com/tonyreina/ai_governance_healthcare/blob/main/app/frameworks/optica/framework.json),
apart from the two items named in section 7. The per-item view is generated
from it into section 7 and onto the
[OPTICA checklist](frameworks/optica-checklist.md) page.
