# Exports

A review leaves the dashboard in four ways, each for a different reader.

| Export | For | Format | Language |
|---|---|---|---|
| **Report** | A board, an auditor, a regulator, an insurer | Standalone HTML, PDF, or Markdown | The reader's, and it says which |
| **Project data** | A script, another copy of the tool, or an analyst | JSON, one file per project | English |
| **Portfolio** | A spreadsheet | CSV, one row per project | English |
| **Dataset metadata** | A repository that indexes datasets | Croissant JSON-LD, made by a Python script | English |

The report buttons are on the *Report* step: **Download report (HTML)**,
**Download PDF**, **Download Markdown** and **Download project data (JSON)**.
The portfolio CSV is on the home page.

## What every export says about where it came from

A copy that has left the tool is easy to mistake for the record. So each export
says which storage mode produced it, in the header's own words: *This browser
only* or *Shared workspace*, with a sentence on what that mode does and does
not guarantee. In the report it is a note at the end. In the JSON
it is a `storage` object with the mode, the label and the note. In the CSV it is
a **Stored in** column.

That storage note is safety-bearing: in a language whose translation has not been
reviewed, it stays in English in the report (see
[Developing it](developing.md#languages)).

A report is also tied to the record it came from by the **record
fingerprint**, which every export carries: a SHA-256 and an MD5 of the project.
The JSON has them in a `fingerprint` object, with the project's id beside it; the
HTML report, the PDF it prints and the Markdown report print them at the end. The
MD5 is the one the project's setup page and change log show, so a fingerprint
quoted beside a report ties it to the record on screen.

The fingerprint shows whether two copies are the same version. It does not prove
nobody altered the record: anyone who can edit a file can recompute its hash, so
a hash proves tampering only if it was kept somewhere the editor could not reach,
such as in your own records system when the report was filed. SHA-256 is the
digest to quote for that; MD5 has been collision-broken since 2004 and is a
version label, not a seal.

You can check a JSON export against its own fingerprint:

```bash
python examples/load_export.py my-project-chai-review.json
# ...
#   fingerprint: SHA-256 3f1a9c0e5b7d2a46...  matches the record
```

It recomputes both digests from the file alone, over the record (the `_state` and
the project id) as compact canonical JSON in UTF-8: keys sorted at every level,
by UTF-16 code unit as JavaScript sorts them (so `"10"` comes before `"9"`, and
an emoji before a character from U+E000 to U+FFFF), with the volatile fields
`updatedAt`, `updatedBy`, `cardUpdatedAt`, `_state`, `contentHash` and
`generated` left out. Strings are written as JavaScript's `JSON.stringify` writes
them, so a lone surrogate (half of a pair, alone, which a JavaScript string can
hold and UTF-8 cannot encode) is written as its lowercase `\u` escape, such as
`\ud800`. An export from before fingerprints were added reports that it has none.
It reads the export of a build of any framework, not only CHAI's.

The record is the one as stored. A record an older version of the dashboard
saved can lack fields the dashboard now fills in to show it (such as
`meta.chaiUseCase`); the fingerprint, and the export's `_state`, are of the
record without them, as the server holds it.

On the shared server, each revision in the version history carries the MD5 of
the record as it was, computed by the same rule, so a revision's fingerprint is
the one the setup page and an export showed for that record. Revisions saved
before this rule was fixed (#177) were hashed without the project's id, and their
fingerprints do not match. The server refuses a record holding a lone surrogate,
which PostgreSQL cannot store.

On the shared server, the dashboard reports each export it produces, so it
appears in the read trail beside the reads that fetched the data
([Cloud deployment](deploy.md#the-read-trail)). That is a record of ordinary
use, not a control: a modified client could omit it.

Whatever a person typed stays text in every export. In the HTML report and the PDF
it is escaped, in the Markdown report it is ended at the line and has the
characters Markdown reads as structure escaped, so a value cannot start a heading,
become a link or an image, or add raw HTML, and in the CSV a cell a spreadsheet
would run as a formula is neutralized. The test suite renders the Markdown report
with CommonMark and GFM renderers, with raw HTML passed through as well as refused,
and audits the HTML that comes out; it does not run GitHub's own renderer or a
particular editor's preview.

What a person types becomes formatting or a link in two places only: the [notes
and rationale fields](guide.md#formatting-notes), which take bold, italic, lists
and http(s) links, and the address of an [evidence
reference](guide.md#evidence-references). Only an http or https address becomes
a link in either. The HTML report links it with `rel="noopener noreferrer
nofollow"` and prints the address beside it; the Markdown report writes it as a
link with its parentheses encoded, and prints the address after it. A
reference's file is listed by name, size and SHA-256, never included.

## The report

The report has the status and its flags, readiness by stage and by principle, the
checkpoint decisions and who recorded them, the open gaps with their owners and
due dates, the applied model card, the sign-off history and, in an appendix, the
whole checklist. It closes with a disclaimer: it is an internal governance record,
not a certification, legal opinion or regulatory determination.

### PDF

**Download PDF** opens your browser's print dialog on the standalone report;
choose *Save as PDF*.

!!! note "Why the print dialog rather than a one-click download"

    No PDF library is bundled. Every option weighs hundreds of kilobytes, and
    the dashboard has to stay one self-contained file small enough to read in
    one sitting: a PDF writer would be larger than the whole application.

    Browsers already render HTML to PDF well, with real fonts, selectable text
    and working links. A canvas-based library gives you an image of a document
    instead.

What gets printed is exactly the standalone HTML export, rendered in an
offscreen frame, not the page you are looking at. So the PDF and the HTML
download are the same document, and the app's own navigation never appears in
it. It is also the one export that keeps working where file downloads are
unavailable, since it goes through the print dialog rather than a download API.

## Project data (JSON)

Each project exports as JSON, described by
[`schema/project.schema.json`](https://github.com/tonyreina/ai_governance_healthcare/blob/main/schema/project.schema.json).
The file holds the status, phase, next review date and flags
as computed at export time; the project's `meta`, checkpoint decisions and metrics;
the model card; the whole checklist with each criterion's status, evidence, owner,
due date and `references`; the scores; and `_state`, the project as the tool
stores it. A flag's `text` is English, its dates included ("Periodic review due
Sep 5, 2026"), whatever the language of the dashboard that exported it; the
portfolio CSV's flags are the same text.

The `schema` field names the framework: `chai-review/2` for the published build,
and the definition's own id, of the form `<id>-review/<n>`, for a [build of
another framework](frameworks/custom.md). One schema describes every framework's
export, because the structure is the same. Where a value comes from the
framework's definition (item ids, statuses, categories, phases, checkpoints,
model card fields and supplements), the schema lists it for CHAI; for the
example framework's build (`example-review/1`) it lists the record's keys and an
answer's fields, and says it has no model card; another framework's values are
the ones in its definition. An answer holds a status, evidence, an owner, a due
date and references, and the reason a status asks for under the field the
definition names: for CHAI and the example framework any other field is refused,
while another framework's answer may hold any text field, since the schema
cannot know its reason field's name. Every field the export always writes is
required.

CI validates against the schema the exports of every sample of the published
build and of the example framework's build, in English and in every other
language the dashboard offers (each the same file as the English one), and, in
English, an empty project, one with hostile text in every typed field, and
records with evidence references, OPTICA's answers, access lists and a review
due soon. It also fails on a field one of those exports writes and the schema
does not describe, on any field the export always writes that the schema does
not require, and on any field the schema describes that none of those exports
writes, unless the test lists it with the reason. An export from before the
provenance and the fingerprint were added (#93, #150) lacks them, and the schema
no longer describes it.

Only `_state` is read back. Everything else is derived for the reader's
convenience. **Import project JSON** on the home page reads `_state` and creates
a **new** project.

!!! note "Import creates a new project"

    Importing does not merge into the project the file came from: it creates a
    separate one. Retire or delete the original if you meant to replace it.

## Portfolio (CSV)

**Export portfolio (CSV)** writes one row per project, as the dashboard shows
it: project, developer, clinical sponsor, risk tier, lifecycle phase, status,
readiness, next review, flags, whether it is archived, when it was last updated,
and where it is stored.

## Reading an export in Python

Four scripts in `examples/` work on exports. Run them from the repository root.

```bash
python examples/load_export.py my-project-chai-review.json
```

prints a summary of the project, checks its fingerprint and, for a CHAI export
with pandas installed, lists its open gaps.

### Feeding evaluation metrics back in

`fairlearn_to_metrics.py` and `error_cohorts_to_metrics.py` are libraries, not
commands. They append your evaluation results to an export's key metrics, so they
flow into the model card:

```python
from fairlearn.metrics import MetricFrame
from sklearn.metrics import recall_score
from fairlearn_to_metrics import load, add_metrics, metricframe_to_rows, save

mf = MetricFrame(
    metrics={"Sensitivity": recall_score},
    y_true=y_test,
    y_pred=y_pred,
    sensitive_features=X_test[["age_band", "sex"]],
)
export = load("deterioration-index-chai-review.json")
add_metrics(export, metricframe_to_rows(mf))
save(export, "deterioration-index-with-fairness.json")
```

`error_cohorts_to_metrics.py` goes looking for subgroups nobody pre-specified. It
fits a shallow decision tree to the model's *errors*, so the leaves describe where
the model goes wrong, and writes the cohorts that fare materially worse than the
whole as metric rows with their size. A cohort found this way is a lead to
investigate, not a finding: it does not show a disparity is unfair or causal, and
small cohorts are noisy. Both scripts need `pandas`; the first needs `fairlearn`
and the second `scikit-learn`.

Re-import the resulting file from the dashboard with **Import project JSON**.

## Croissant

`croissant_export.py` converts a project export into
[Croissant](https://docs.mlcommons.org/croissant/) 1.0 metadata with the
[Responsible AI extension](https://github.com/mlcommons/croissant/blob/main/docs/croissant-rai-spec.md),
so a governance record can be published as machine-readable dataset metadata.

```bash
python examples/croissant_export.py my-project-chai-review.json -o dataset.jsonld
```

The output validates against `mlcroissant`.

### What it describes, and what it refuses to

Croissant describes a **dataset**. A governance record describes a **model** and
an **organizational process**. The exporter keeps that distinction rather than
blurring it:

- `name` and `description` describe the *development and validation data
  extract*.
- The solution itself is carried under `about` as an `sc:SoftwareApplication`.
- The governance record is linked via `isBasedOn`, not transcribed.
- Four governance facts are emitted in this project's own
  [`chai:` namespace](ns/index.md).

The checklist, the checkpoint decisions and the readiness scores are **not**
exported. Croissant has no vocabulary for assurance attestations, and
`sc:creativeWorkStatus` describes the editorial status of a work, not a
governance body's decision to expose patients to a model.

!!! warning "Cohort detail is withheld by default"

    `rai:dataCollection` carries cohort size, dates, sites and demographics by
    design, and Croissant files exist to be published and indexed. A small-cell
    cohort description attributed to a named organization can be re-identifying.

    Pass `--include-cohort-detail` to emit it. Check for small cells first.

!!! warning "People are not named by default"

    The review team and clinical sponsor are personal data, and a published
    record that names them links identified individuals to a named clinical
    system, a site and a time. By default `maintainer` is an organizational
    contact (*AI Governance Committee, <your organization>*), or is left out when
    no organization is recorded.

    Pass `--include-maintainer-names` to publish the review team (or, if there is
    none, the sponsor) by name. The exporter then prints a warning that lists
    exactly what it published.

### No fabricated structure

The exporter emits no `distribution` and no `recordSet`. A governance record
contains no file hashes, no content URLs and no column names, and synthesizing
them to satisfy a validator would manufacture provenance for clinical data the
tool has never seen. Croissant 1.0 accepts a metadata-only record.

For the same reason it asserts no `license` for the data, only `sdLicense` for
the metadata record. `mlcroissant` warns that `license` is recommended; that
warning is correct, and a human should answer it.

### BioCroissant

[BioCroissant](https://github.com/mlcommons/BioCroissant) is the biomedical
extension of Croissant. As of this writing its repository is a **skeleton**:
its own READMEs state "no schema files yet" and "no implementation yet".

A draft `bio:` vocabulary exists in the prototype its READMEs point to,
[biocroissant-to-omop](https://github.com/renato-umeton/biocroissant-to-omop),
which marks itself `PLACEHOLDER` because the context IRI
`https://mlcommons.org/croissant/bio/0.3/context` does not resolve.

```bash
python examples/croissant_export.py export.json --profile biocroissant-draft
```

This is **off by default and experimental**. Emitting terms under a prefix that
does not resolve is a real defect in published linked data, defensible only as a
labeled opt-in. The output carries a `_contextNote` saying so, and still
validates. `conformsTo` is an array from the start, so adopting BioCroissant
properly later means appending one string.
