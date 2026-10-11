# OPTICA checklist

All 77 OPTICA items, with what each asks and how far the
[CHAI criteria](chai-checklist.md) reach it.

!!! warning "These are paraphrases, not the OPTICA checklist"

    The OPTICA paper is copyrighted and marked *for personal use only*, so
    its item text is **not** reproduced here. Every line below is an
    original summary written for this project, describing what the item
    asks for.

    They are a navigation aid. Completing a real OPTICA review means
    working from the paper, including Table S1 in its Supplementary
    Appendix — the authors state the checklist should not be completed
    without it. See [Notice & license](../notice.md).

## How to read the CHAI column

| Label | Meaning |
|---|---|
| **OPTICA only** | No CHAI criterion asks for any part of this |
| **partial** | CHAI touches it but asks for materially less, or asks a different party |

There are no *equivalent* rows. No OPTICA item fully discharges a CHAI
criterion — see the [crosswalk](../crosswalk.md) for why that matters.

**Who answers** is the other column that decides whether evidence can be
shared: `adopter` means only the adopting organization can answer,
`developer` means only the solution's vendor or builder can.

## Domain A: Clinical need specification

### Chapter 1: Defining the clinical need

*Pin down, in concrete terms, the care problem the proposed AI system is
supposed to fix, how work is done today versus how it would be done
afterwards, what the system must emit, and the measurable bar it has to clear
to be worth adopting.*

*6 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **1.1** | State the specific care-delivery problem that this system is meant to address. | adopter | partial — `s1-1`, `s1-4` |
| **1.2** | Describe how this task is handled today — who decides what, at which points, using which information — and spell out the harms, costs, or inefficiencies the status quo produces. | adopter | partial — `s1-2`, `s1-3` |
| **1.3** | Lay out the revised workflow as it would run once the AI system is in place. | adopter | partial — `s2-1`, `s2-2`, `s2-5` |
| **1.4** | Say what kind of result the system is expected to produce — generated prose, a probability or category derived from input data, or an estimate of how an outcome would shift under a given intervention — bearing in mind that each of these commits the project to a different analytic approach. | adopter | partial — `s2-2` |
| **1.5** | Which performance measures actually matter for this use, and how good do the numbers have to be before adoption is defensible? Statistical or data-science input is worth soliciting here. | adopter | partial — `s1-3`, `s2-4` |
| **1.6** | Can the gain expected from rolling this out be expressed in numbers? | adopter | partial — `s1-3`, `s6-6`, `s5-3` |

### Chapter 2: Exploring alternative solutions

*Check the proposed system against everything else that could meet the same
need, so the choice rests on a documented comparison rather than on the first
option that came to the organization's attention.*

*3 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **2.1** | Survey what else already addresses this need — commercial offerings, approaches reported in the literature, and tools built in-house — and record what each one does and what it would cost. Procurement or business-development help may be useful here. | adopter | partial — `s1-2` |
| **2.2** | Where alternatives do exist, how do they compare on performance, and does any of them clear the bar set in item 1.5? | adopter | OPTICA only |
| **2.3** | When more than one option would be acceptable, what actually separates them? Identify what each brings that the others do not, and any distinguishing feature that tips the decision toward one of them. | adopter | OPTICA only |

## Domain B: Data exploration

### Chapter 3: Population characterization

*Establish who the model was built on and whether those patients plausibly
stand in for the people this organization would actually run it on.*

*6 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **3.1** | Identify whose records went into building the model: the eligibility and disqualification rules that bounded the cohort, plus a profile of the care environment those patients were drawn from. | developer | partial — `s3-1` |
| **3.2** | State how many patients the development cohort contained. | developer | OPTICA only |
| **3.3** | Summarize what that cohort looked like, reporting the spread of its principal variables the way a baseline-characteristics table would. | developer | partial — `s3-2` |
| **3.4** | Explain the partitioning scheme that separated patients into fitting, tuning, and held-out evaluation groups. | developer | OPTICA only |
| **3.5** | Check that each subgroup whose care could differ was represented in sufficient numbers to support a claim about it. Which subgroups matter is use-case specific, and typically includes disease severity strata, deprivation or payer status, and the usual demographic axes. | developer | partial — `s3-2`, `s2-3` |
| **3.6** | From a clinician's standpoint, decide whether the people and care context behind the model's training and testing resemble the patients this organization would apply it to. | adopter | partial — `s4-1`, `s1-4`, `s3-2` |

### Chapter 4: Input data

*Pin down exactly what the model consumes, then verify the organization can
supply all of it, in the right form, at the moment of execution.*

*10 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **4.1** | Enumerate every variable the model consumes, and for the development data describe how each was captured and how its values were spread. | developer | partial — `s3-1` |
| **4.2** | Specify the shape and encoding in which the model requires its inputs to arrive. | developer | OPTICA only |
| **4.3** | Pin down the moment in the care process at which the model is meant to fire, which doubles as the cutoff beyond which no input may be used. | developer | partial — `s2-2`, `s2-1` |
| **4.4** | Describe the treatment of absent values when the model was fitted, and prescribe how absences should be treated once it is running live. | developer | partial — `s3-4` |
| **4.5** | Describe the treatment of out-of-range or outlying values during fitting, and the rule to apply to them in production. | developer | partial — `s3-4` |
| **4.6** | From a clinical viewpoint, judge whether the model is being fed the information a clinician would consider essential for the job it is meant to do. | adopter | OPTICA only |
| **4.7** | Audit the organization's own data holdings for each input the model needs, confirm they can be supplied in the required encoding, and profile how those variables are distributed and captured locally. | adopter | partial — `s1-7`, `s4-1` |
| **4.8** | Confirm each required input will actually be on hand at the moment and in the setting where the model is supposed to run, not merely present somewhere in retrospective archives. | adopter | partial — `s2-7`, `s4-4` |
| **4.9** | Weigh whether the value distributions of the developer's training inputs sit close enough to the locally observed ones for a clinician to be comfortable. | adopter | partial — `s4-1`, `s6-1` |
| **4.10** | Weigh whether the way the training inputs were generated and recorded matches how this organization generates and records them. | adopter | partial — `s3-1` |

### Chapter 5: Output data

*Characterize what the model emits and the target it was trained against, then
check that same target exists locally and behaves similarly.*

*6 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **5.1** | State what the model emits, in two parts: the substance of the result (for example a written summary, a continuous risk estimate, or a category assigned to a clinical finding) and its data type (free text, numeric, or categorical). | developer | partial — `s2-4` |
| **5.2** | Explain how the target the model learns to produce was operationalized, and give its key descriptive properties, for example how frequently the labeled event occurred. | developer | partial — `s3-1` |
| **5.3** | Where the model forecasts something, state the window over which the forecast event was ascertained. | developer | OPTICA only |
| **5.4** | Judge clinically whether the target the model was taught to produce, as characterized in the three preceding items, is both pertinent to the stated need and dependable as a label. | adopter | partial — `s1-1` |
| **5.5** | Determine whether the organization's own data carry the model's target variable too, and if so profile it against the properties the developer reported. | adopter | partial — `s4-1`, `s1-3` |
| **5.6** | Weigh whether the target's distribution locally sits close enough to the developer's reported distribution for a clinician to accept. | adopter | partial — `s4-3`, `s2-4` |

## Domain C: Development & performance evaluation

### Chapter 6: Development process

*Open up how the model was actually built so that a reviewer can judge whether
the training methodology was sound and free of the classic traps that inflate
apparent quality.*

*6 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **6.1** | Describe the modeling approach behind the solution and how it was fitted — which family of algorithm it belongs to and what the training procedure looked like. | developer | OPTICA only |
| **6.2** | Confirm that the algorithm class chosen is a sensible match for the kind of output the solution emits. | developer | OPTICA only |
| **6.3** | Where the solution forecasts a future event, explain how subjects whose observation ended early were treated during training, and confirm that this was handled deliberately rather than by default. | developer | OPTICA only |
| **6.4** | Explain the safeguards that kept information about the outcome from contaminating the predictor variables, and confirm this risk was actively tested for rather than assumed away. | developer | OPTICA only |
| **6.5** | Describe what was done to detect and reduce inequitable or skewed behavior across groups, and confirm the issue received deliberate attention during development. | developer | partial — `s3-3`, `s4-2` |
| **6.6** | State whether practicing clinicians and other subject-matter specialists took part in building the solution, and in what capacity. | developer | partial — `s2-1`, `s1-1` |

### Chapter 7: Performance

*Establish what the solution's accuracy actually is — as reported, as
benchmarked against alternatives, as re-tested on local data, and as observed
in a pilot — and whether it clears the bar the clinical lead set at the
outset.*

*12 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **7.1** | Report how well the solution scored on historical data, using measures appropriate to the kind of model it is. | developer | partial — `s4-3` |
| **7.2** | Break those measured results down across the patient subgroups that matter clinically. | developer | partial — `s4-2` |
| **7.3** | Characterize the dataset on which these results were measured. | developer | partial — `s3-1`, `s3-2` |
| **7.4** | State whether the evaluation sample preserves the real-world balance of outcomes or was deliberately resampled, since rebalancing distorts any metric that depends on how common the outcome is. | developer | OPTICA only |
| **7.5** | Report any evaluation carried out in settings beyond the one that supplied the training data, and what the results were there. | developer | OPTICA only |
| **7.6** | Share any evidence of how the solution has behaved in live clinical use elsewhere, including where that experience comes from. | developer | OPTICA only |
| **7.7** | Judge whether the reported results clear the metric thresholds the clinical lead specified when the need was first defined. | adopter | partial — `s1-3` |
| **7.8** | Assess whether these results look credible and competitive when set beside the alternative solutions surveyed earlier. | adopter | OPTICA only |
| **7.9** | Determine whether the organization's own historical records could support an in-house evaluation of the solution, and estimate what mounting one would cost in effort. | adopter | partial — `s1-7`, `s4-1` |
| **7.10** | If an in-house retrospective test goes ahead, confirm whether the data it would consume match exactly what the live system would actually receive at runtime. | adopter | partial — `s4-4` |
| **7.11** | Where a local retrospective test was actually carried out, give the clinical verdict on whether its results were good enough. | adopter | partial — `s4-1` |
| **7.12** | Where a limited trial run was judged worthwhile before full rollout, summarize what it revealed about accuracy, day-to-day workability and how users received it. | adopter | partial — `s5-2`, `s5-3` |

### Chapter 8: Explainability

*Determine whether the solution can account for its outputs both model-wide
and case by case, and whether those accounts stand up to clinical scrutiny.*

*3 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **8.1** | Identify which variables drive the model's behavior overall, or account for why such a ranking cannot be produced. | developer | OPTICA only |
| **8.2** | State whether the solution can justify the result it produces for one specific case, and illustrate with worked examples spanning different kinds of patients. | developer | partial — `s4-6` |
| **8.3** | Give a clinician's verdict on whether the model-wide and per-case explanations hold up medically. | adopter | partial — `s4-6` |

### Chapter 9: Regulations, data security & privacy

*Confirm the solution can be fielded lawfully and safely — regulatory
conformity, honesty with patients, protection of data against attack, and
respect for privacy rules.*

*4 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **9.1** | Establish whether the solution satisfies the regulatory rules that apply in this jurisdiction and this institution, drawing on legal counsel and the information security lead. | adopter | partial — `s1-7` |
| **9.2** | Decide whether patients are told clearly enough that an algorithm plays a part in their care, with legal input on what disclosure is actually owed. | adopter | partial — `s5-6`, `s1-7` |
| **9.3** | Verify that the solution meets the institution's requirements for safeguarding data and withstanding attack, with the information security lead involved. | adopter | partial — `s4-7`, `s2-7` |
| **9.4** | Confirm that the solution's handling of identifiable information satisfies the privacy rules that apply locally, again with the information security lead involved. | adopter | partial — `s1-7`, `s3-6` |

## Domain D: Deployment & monitoring plan

### Chapter 10: Deployment plan

*Pins down how the solution will actually be wired into clinical work and into
the organization's technical stack - where it surfaces, who acts on it, and
what has to be built to serve it.*

*7 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **10.1** | Pinpoint where along the care pathway the tool fires - which encounter, decision point, or step of the existing process it attaches to. | adopter | partial — `s2-2`, `s2-1` |
| **10.2** | Name the host application or screen where clinicians will actually see the result, and describe how using it is meant to feel day to day - how discoverable it is, how many clicks it costs, how reliably it is on hand. | adopter | partial — `s2-1`, `s5-2` |
| **10.3** | State whether a named human clinician stands between the model and the patient, owning the choice to act on a result or set it aside. | adopter | partial — `s2-5`, `s1-6` |
| **10.4** | If each result has to arrive with its rationale attached, work out how that supporting explanation gets rendered inside the host system next to the result itself. | adopter | partial — `s4-6` |
| **10.5** | Determine whether fresh interfaces or middleware must be built to carry results from whatever serves the model over to the system that will display them. | either | partial — `s2-7`, `s4-5` |
| **10.6** | Identify the host hardware the model will execute on and confirm its compute and memory headroom are adequate for the expected load. | either | partial — `s4-5` |
| **10.7** | Confirm that every input feed reaches that execution environment promptly enough to be useful, and flag which feeds must arrive live rather than on a batch schedule. | either | partial — `s3-4`, `s2-7` |

### Chapter 11: Monitoring plan

*Establishes how the system will be watched once live, so that drift in its
inputs, its outputs, its accuracy, or the underlying medical knowledge is
caught rather than discovered late.*

*6 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **11.1** | From the builder's standpoint, state the cadence at which the model has to be refreshed or refit. | developer | partial — `s6-3` |
| **11.2** | Say whether the system refits itself automatically in the field, and if it does, describe how each refreshed version's quality gets verified before it influences care. | developer | partial — `s6-3` |
| **11.3** | Lay out how incoming feature values will be watched for drift or outright breakage once the system is running. | either | partial — `s6-1`, `s3-7` |
| **11.4** | Lay out the equivalent watch on what the model emits, so that shifts in the distribution of its results surface early. | either | partial — `s6-1`, `s6-4` |
| **11.5** | From the clinical side, state how often the medical content baked into the solution - guidelines, thresholds, standards of care - needs refreshing. | adopter | partial — `s6-3` |
| **11.6** | Set out how the solution's accuracy will keep being measured after go-live, not only before it. | adopter | partial — `s6-1`, `s6-2`, `s3-7` |

### Chapter 12: Evaluation plan

*Settles in advance how the deployment's real-world benefit and harm will be
measured, fed back and reported.*

*5 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **12.1** | Define what counts as success for this rollout - the outcome measures the deployment itself will be judged on. | adopter | partial — `s1-3` |
| **12.2** | Describe the study design that will test whether the rollout genuinely helped - and whether it harmed anyone along the way. | adopter | partial — `s5-3`, `s5-5`, `s1-3`, `s6-6` |
| **12.3** | Check whether the rollout itself can be structured up front - staggered, randomized, phased by site - so that its effect can later be measured credibly. | adopter | partial — `s5-1` |
| **12.4** | Decide how you will capture what users actually think of it - perceived usefulness, friction, trust. | adopter | partial — `s5-2`, `s6-6` |
| **12.5** | Decide who writes up the evaluation findings, how often, and to whom they go. | adopter | partial — `s6-3`, `s2-6` |

### Chapter 13: Organizational AI strategy fit

*Gives the organization's AI leadership the final word on the quality of the
answers, the merit of the solution, and its fit with the wider AI strategy.*

*3 items.*

| | What it asks | Who answers | CHAI |
|---|---|---|---|
| **13.1** | Step back and judge how well the rest of the checklist was actually answered - depth, candor, and what was left open. | adopter | OPTICA only |
| **13.2** | Give an overall opinion on the proposed system itself, and on whether it genuinely answers the need stated at the very outset. | adopter | partial — `s1-2`, `s1-6` |
| **13.3** | Judge the fit with where the organization is heading on AI overall, including knock-on effects that reach beyond this one deployment. | adopter | OPTICA only |

## Source

Dagan N, Devons-Sberro S, Paz Z, et al. *Evaluation of AI Solutions in Health
Care Organizations - The OPTICA Tool.* NEJM AI 2024;1(9). [DOI:
10.1056/AIcs2300269](https://doi.org/10.1056/AIcs2300269)
