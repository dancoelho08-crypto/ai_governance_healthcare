#!/usr/bin/env python3
"""Fail if a file uses British spelling where American is wanted.

This project is written in American English: it is built around CHAI, a US
non-profit, and aimed at US health systems, so British spellings read as
inconsistent with the subject matter. The slips are easy to miss in review
because words like "behavior" and "defense" look unremarkable.

Nothing is ever written. The check reports; --fix (pixi run fix-spelling)
prints a patch of suggestions for a person to review and apply, and a list of
the hits it has no suggestion for. Five rounds of review showed that a tool
rewriting the owner's files by heuristics keeps corrupting text it misreads
(a genus in emphasis, a link's label, <pre> and <script>, front matter,
templates, package names, French, quotations), so no path writes a file.

What is reported
----------------

Reporting is broad: a false report costs a ``spelling-ok`` marker, and a missed
one costs the rule. Every hit is reported, whatever word stands before it.

* A listed word, in any case. The list is of roots, not of words: each root's
  inflections (plurals, -ed, -ing, -er, the -isation family, un-, re- and the
  like) are generated from it, because a list of exact forms missed
  "judgements" while it listed "judgement" (#169). The British medical
  spellings are roots too (MEDICAL: "haemorrhag-", "oedem-", "oesophag-", the
  -aemia words and the rest), each with a closed set of English endings and a
  few known prefixes, and the -our and -re roots take a few closed compounds
  ("colourblind", "harbourmaster", "centrefold", "theatregoer"). A listed word
  is matched whole, so "phytoestrogen" and "proestrus" are not touched. No
  listed ending is one of the Latin endings -alis, -ium, -icus, -ica, -ae or
  -ensis, so "faecalis" and "gonorrhoeae" are never listed; a few listed English
  words do end in a Latin-looking -us or -i ("foetus", "oestrus",
  "oesophagus", "oesophagi").
* A lowercase word by its shape: it holds a British medical segment anywhere
  in it (SHAPES: haem, oedem, oesophag, oestr, foet, faec, caec, paed, aesthe
  after an-, kin-, syn-, par-, dys-, hyper-, hypo-, hyp- or cen- (so every
  anaes- word), gynae, the British leuco- stems (leucocyt-, leucopen-,
  leucodystroph-, leucotom-, leucotrien-, leucopoie-, leucoencephal-,
  leucoplak-, leucoderm-, leucaem-; leucorrhoea is caught by -rrhoe-), aetio,
  palaeo, praecord, pharmacopoei, spirochaet, sulph, tumour, -rrhoe-, -pnoe-,
  -aemia and -aemic; and -litre and -gramme at its end), and is longer than the
  segment. See by_shape(). A segment that an American word can hold by accident is
  narrowed: oe- segments count only at the start or after "a", "i", "o" or
  "y" ("videoedema" and "phytoestrogen" are American), "haem" inside a word
  only before "a" or "o" ("alphaemission"), "foet" only before an English
  ending ("infoetl"), "aesthe" only after those prefixes ("aesthetic",
  "nonaesthetic"), "leuco" only in those stems ("leucocratic", "leucoplast").

A word found by its shape is not reported when:

* it is spelled with the letters a-f alone (hex: "#faecab");
* it has a Latin ending (-us but not -ous, -ae, -ii, -alis, -icus, -ica, -icum,
  -ensis) or is one of LATIN_EPITHETS, Latin epithets whose ending looks
  English ("faecium", "haematobium");
* it contains one of SHAPE_EXCEPTIONS, words American biology spells this way
  ("caecilian", "paedomorphosis", "oestrid", "asafoetida"), or is one of
  DICTIONARY_WORDS, which the en_US dictionary accepts as American
  ("leucotomy", "pharmacopoeia").

And no word, listed or found by its shape, is reported when it is the epithet
of a binomial (see binomial()): it is a Latin epithet (epithet()): it ends in
a Latin form (-a, -i, -is, -um, -us but not -ous), does not end in an
English medical form (-ia, so every -aemia; -oea, so every -rrhoea and -pnoea;
-oma; -itis; -sis), and is not a listed word, except "foetus"
(LISTED_EPITHETS), and is not one of NOT_EPITHETS (English -um and -a nouns
that look Latin: "caecum", "haemoperitoneum", "haemopericardium",
"haematometra", "praecordium"); and the word before it, past markup such as "*",
"_" and HTML tags, and on the line before if it is first on its line, is one of
GENERA or an abbreviated genus. An abbreviated genus is exactly one capital
letter and a period, the capital standing at the start of the text or directly
after whitespace, "*", "_", a quote or an opening bracket (so "UK." and
"Fig. 2A." are none), and the word before the capital is none of
NOT_GENUS_WORDS (Dr, Mr, Mrs, Ms, Prof, Hep, Group, Twin, Fig, Figure, Bed,
Lead, Vitamin, Appendix, Table, Type, Grade, Stage, Class, Factor, Hepatitis,
Genotype, in any case; "Twin A. foetus" is reported). So "Tritrichomonas
foetus", "T. foetus", "S. haematobium" and "Enterococcus faecalis" pass, and
"Severe foetus", "Staphylococcus bacteraemia", "Neisseria gonorrhoea",
"Mycoplasma oesophagitis", "Clostridium caecum", "Hep B. foetus", "Dr K. foetus"
and "B. oedema" are reported. A British word after a genus is reported, then,
except a true epithet: LATIN_EPITHETS (listed whole, wherever they stand,
including "haemolysans", "oedematiens", "haemobos", "haemophilum" and
"caecicola"), a word with a Latin ending, or "foetus" after a genus. The genus
list is closed: an epithet after a name not in GENERA is reported, and needs a
marker.

Known limits: a British word that neither the list nor a shape covers passes
(tests/fixtures/spelling_corpus/unlisted.txt keeps a few); a word spelled with
the letters a-f alone is hex and is not read, so "caeca" passes; "sulphur" is
reported wherever it stands, the butterfly's name included, because it is the
British spelling of "sulfur" and a marker is the way to keep it; and a
commit message, which the check does not read. A word with an accented letter
is not English and is not read ("décentre").

Not prose, so not reported: a URL (with "://", or one of the schemes written
without it, such as mailto:, urn:, doi: and data:, starting after anything but
a letter or digit), an email address, a domain, a file name with a known
extension, a path, a digest ("sha384-..."), and a run of 16 or more characters
that looks like encoded data (see looks_encoded()). An abbreviation written
with dots ("e.g.", "i.e.") is not a file extension, so "oedema/e.g." is prose.

Words are read the way code writes them, so the parts of an identifier
(``colourPicker``, ``MAX_COLOURS``, ``data-colour-id``) are reported too, in any
case, and the ligatures "œ" and "æ" are read as "oe" and "ae".

The suggestion patch
--------------------

--fix never writes a file; there is no flag that makes it. It prints to stdout
a unified diff, which ``git apply`` takes, of suggested respellings, under a
header saying the patch is a suggestion to review before applying. Paths are
relative to the repository root. A file outside it is named as given when that
is a relative path that does not climb (".."), for `git apply` to take from
where the command ran; one named by an absolute path or with ".." cannot be
named (git apply refuses those paths), so its suggestions are left out of the
patch, said so on stderr, and make the exit 1. It
prints to stderr every other hit, for a person to fix by hand, with the reason
it is not in the patch, and exits 1 when there is any hit or a file it cannot
read.

A hit is suggested in the patch only when all of these hold (left_by()); its
imperfection is harmless, because a person reviews each hunk:

* it is listed, not found by its shape;
* it is all lowercase (a capitalized word may be a name);
* the file is Markdown, reStructuredText or plain text (.md, .rst, .txt), or
  it is in a value of app/i18n/en.json; never code, configuration or data;
* it is not in code: a fenced or indented Markdown block, a reStructuredText
  literal block or code directive, text between backticks, a line that starts
  with "import ", "from ... import ", "$ ", ">>> " or "... ", or the word after
  "import", "require" or "library";
* between it and the whitespace (or line end) around it there is nothing but,
  before, any of ``( [ " ' *`` and, after, any of ``) ] " ' * , ; : . ! ?``.

Known limits: the patch can still be wrong (a lowercase listed word in a
quotation, a name written in lowercase), which is why it is a suggestion; and
the check reads only what is listed or has a listed shape.

Quoting a source that spells a word the British way is legitimate (R-17), and
nothing here rewrites it. The check still reports it, so mark it:

* Put ``spelling-ok``, in lowercase, in a comment on the same line; that line is
  skipped.
* Add ``glob: phrase`` to ``.spelling-allow`` in the repo root, one per line.
  The phrase, matched exactly and case-sensitively, is skipped in the files the
  glob matches (``*.py``, ``.github/workflows/*.yml``; matched from the right,
  like ``PurePath.match``), and the rest of its line is still checked. ``*``
  matches every file, and needs a comment saying why.

A file that is not valid UTF-8 is reported, not skipped: a check that cannot
read a file has not checked it.

Run with no arguments, it reads every text file under the repository, by the
rule pre-commit's ``types: [text]`` uses for a file it cannot name (see
is_text()), so a whole-repository run and the hook read the same kinds of file:
a shell script, a .caddy file, .env.example and .gitignore as well as code and
documentation. Symbolic links are not read (pre-commit does not pass them; the
target is read on its own), nor anything under SKIP_DIRS. A symbolic link named
on the command line stands for its target: a file named twice (./a.md and
a.md, or through a symbolic link to a directory, or a link and its target) is
read once, so a patch never names one file twice, and a link to no file is said
to be skipped on stderr and makes the exit 1.

tests/test_check_spelling.py pins all of this, against a corpus a verifier
built (tests/fixtures/spelling_corpus/).

Run via: pixi run check-spelling  (suggestions: pixi run fix-spelling)
"""

from __future__ import annotations

import difflib
import os
import re
import sys
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_i18n import Locale

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / ".spelling-allow"

SKIP_DIRS = {
    ".git",
    ".pixi",
    "site",
    ".cache",
    "node_modules",
    ".venv",
    "venv",
    "backups",
    # Output of a build of other frameworks (pixi run build-example), ignored by git.
    "build",
    # Tool caches, ignored by git and never ours to spell.
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
# This file IS the word list. Scanning it would flag every British key.
SELF = Path(__file__).resolve()

# Files that reproduce third-party text verbatim. CHAI's Testing & Evaluation
# content is CC BY 4.0 and quoted exactly; "correcting" its spelling would
# misquote the source, which is worse than an inconsistent spelling. These are
# generated from upstream, so a respelling here would be overwritten anyway.
QUOTED_VERBATIM = {
    "data/chai_te_metrics.json",
    "docs/frameworks/chai-metrics.md",
    "app/js/10-frameworks/10-chai/05-te-metrics.js",
    # The built dashboard concatenates all of the above. Its own sources under
    # app/ ARE checked, so nothing of ours escapes review by being in here.
    "docs/app/index.html",
}
# The test corpus of tests/test_check_spelling.py: British words, and names and
# code that keep a British spelling, each there on purpose. Only the files
# directly in it are skipped.
CORPUS = "tests/fixtures/spelling_corpus"
# The bytes a text file is made of, by the rule of identify, which pre-commit's
# `types: [text]` uses for a file it cannot classify by its name: 0x20-0x7E,
# 0x80-0xFF, and of the control bytes only BEL, BS, TAB, LF, VT, FF, CR and ESC.
# Any other byte (NUL, another control byte, DEL) in the first 1024 bytes makes
# a file binary. Bytes 0x80-0xFF are text, so a Latin-1 file is read, and
# reported as not UTF-8.
TEXT_BYTES = bytes(
    sorted({7, 8, 9, 10, 11, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F})
)

# British -> American, by root. A word list of exact forms catches the forms
# someone thought to type: "judgement" was listed and "judgements" was not, so
# the plural passed (#169). So the list holds roots, and every inflection is
# generated from a root by the endings its family takes, under the prefixes it
# takes. A generated form that is not a real word is harmless: it can only ever
# match a British spelling, because each one keeps the British part of its root.
#
# A family is (endings, prefixes, stems). Each ending is a (British, American)
# pair appended to the stem; each prefix is prepended to both.
Family = tuple[tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]

FAMILIES: dict[str, Family] = {
    # colour -> color: the stem is everything before the "our".
    "-our": (
        (
            ("our", "or"),
            ("ours", "ors"),
            ("oured", "ored"),
            ("ouring", "oring"),
            ("ourings", "orings"),
            ("oural", "oral"),
            ("ourally", "orally"),
            ("ourable", "orable"),
            ("ourably", "orably"),
            ("ourite", "orite"),
            ("ourites", "orites"),
            ("ouritism", "oritism"),
            ("ourer", "orer"),
            ("ourers", "orers"),
            ("ourful", "orful"),
            ("ourfully", "orfully"),
            ("ourfulness", "orfulness"),
            ("ourless", "orless"),
            ("ourly", "orly"),
            ("ourliness", "orliness"),
            ("ourhood", "orhood"),
            ("ourhoods", "orhoods"),
            ("ourism", "orism"),
            ("ourist", "orist"),
            ("ourists", "orists"),
            ("oury", "ory"),
            ("ourise", "orize"),
            ("ourised", "orized"),
            ("ourising", "orizing"),
            ("ourisation", "orization"),
            ("ouration", "oration"),
            # Closed compounds of the commonest roots ("colourblind",
            # "harbourmaster", "flavoursome", "odourant").
            ("ourblind", "orblind"),
            ("ourant", "orant"),
            ("ourants", "orants"),
            ("ourway", "orway"),
            ("ourways", "orways"),
            ("ourmaster", "ormaster"),
            ("ourmasters", "ormasters"),
            ("oursome", "orsome"),
        ),
        ("", "mis", "dis", "un", "re", "water", "multi", "mal"),
        (
            "ard",
            "arm",
            "behavi",
            "cand",
            "clam",
            "col",
            "demean",
            "endeav",
            "fav",
            "ferv",
            "flav",
            "harb",
            "hon",
            "hum",
            "lab",
            "neighb",
            "od",
            "parl",
            "ranc",
            "rig",
            "rum",
            "savi",
            "sav",
            "splend",
            "succ",
            "tum",
            "val",
            "vap",
            "vig",
        ),
    ),
    # centre -> center: the stem is everything before the "re".
    "-re": (
        (
            ("re", "er"),
            ("res", "ers"),
            ("red", "ered"),
            ("ring", "ering"),
            # Closed compounds ("centrefold", "fibreboard", "theatregoer").
            ("refold", "erfold"),
            ("refolds", "erfolds"),
            ("reboard", "erboard"),
            ("reboards", "erboards"),
            ("regoer", "ergoer"),
            ("regoers", "ergoers"),
        ),
        (
            "",
            "kilo",
            "centi",
            "milli",
            "micro",
            "nano",
            "deci",
            "femto",
            "pico",
            "de",
            "re",
            "epi",
        ),
        (
            "calib",
            "cent",
            "fib",
            "goit",
            "lit",
            "meag",
            "met",
            "och",
            "sab",
            "scept",
            "somb",
            "spect",
            "theat",
            "tit",
        ),
    ),
    # defence -> defense.
    "-ce": (
        (
            ("ce", "se"),
            ("ces", "ses"),
            ("ced", "sed"),
            ("cing", "sing"),
            ("celess", "seless"),
        ),
        # No "self": the scan splits "self-defence" at the hyphen, so "defence"
        # is caught, and "selfdefence" is not a word.
        ("", "sub"),
        ("defen", "licen", "offen", "preten"),
    ),
    # organise -> organize, and every form built on it. Only stems whose -ise
    # form is British: "advertise", "exercise", "revise" and the like are
    # American too, so they are not here.
    "-ise": (
        (
            ("ise", "ize"),
            ("ised", "ized"),
            ("ises", "izes"),
            ("ising", "izing"),
            ("iser", "izer"),
            ("isers", "izers"),
            ("isable", "izable"),
            ("isation", "ization"),
            ("isations", "izations"),
            ("isational", "izational"),
        ),
        (
            "",
            "re",
            "un",
            "de",
            "dis",
            "mis",
            "pre",
            "non",
            "over",
            "under",
            "im",
            "neo",
            "hyper",
        ),
        (
            # "anesthet": the American stem with the British ending. The
            # British stem ("anaesthetise") is in MEDICAL.
            "aerosol",
            "alkalin",
            "anesthet",
            "anonym",
            "canal",
            "catastroph",
            "apolog",
            "author",
            "capital",
            "categor",
            "catheter",
            "cauter",
            "central",
            "character",
            "cicatr",
            "civil",
            "colon",
            "commercial",
            "conceptual",
            "container",
            "contextual",
            "critic",
            "crystall",
            "custom",
            "dichotom",
            "digit",
            "emphas",
            "energ",
            "epithelial",
            "equal",
            "external",
            "familiar",
            "femin",
            "fantas",
            "fertil",
            "final",
            "formal",
            "general",
            "global",
            "harmon",
            "heparin",
            "homogen",
            "hyalin",
            "hospital",
            "human",
            "hybrid",
            "hypnot",
            "hypothes",
            "ideal",
            "immun",
            "incentiv",
            "infantil",
            "initial",
            "institutional",
            "internal",
            "isomer",
            "ion",
            "item",
            "keratin",
            "jeopard",
            "lateral",
            "legal",
            "legitim",
            "local",
            "lutein",
            "lyophil",
            "marginal",
            "masculin",
            "material",
            "maxim",
            "medical",
            "memor",
            "mental",
            "metabol",
            "metastas",
            "mineral",
            "minim",
            "mobil",
            "modern",
            "moistur",
            "monet",
            "national",
            "nebul",
            "neutral",
            "normal",
            "operational",
            "opson",
            "optim",
            "organ",
            "oxid",
            "parameter",
            "parametr",
            "patholog",
            "pasteur",
            "patron",
            "penal",
            "personal",
            "polar",
            "polymer",
            "popular",
            "pressur",
            "priorit",
            "privat",
            "pseudonym",
            "public",
            "random",
            "rational",
            "real",
            "recogn",
            "regular",
            "sanit",
            "scrutin",
            "sensit",
            "serial",
            "social",
            "somat",
            "solubil",
            "special",
            "stabil",
            "standard",
            "steril",
            "stigmat",
            "subsid",
            "summar",
            "symbol",
            "sympath",
            "synchron",
            "synthes",
            "theor",
            "token",
            "traumat",
            "trivial",
            "util",
            "vapor",
            "vascular",
            "victim",
            "viril",
            "virtual",
            "vital",
            "visual",
            "weapon",
        ),
    ),
    # analyse -> analyze. Not "-yses": "analyses" is the plural of "analysis".
    "-yse": (
        (
            ("yse", "yze"),
            ("ysed", "yzed"),
            ("ysing", "yzing"),
            ("yser", "yzer"),
            ("ysers", "yzers"),
        ),
        ("", "re", "over", "psycho"),
        (
            "anal",
            "autol",
            "catal",
            "cytol",
            "dial",
            "electrol",
            "hydrol",
            "paral",
            "plasmol",
            "thrombol",
        ),
    ),
    # travelled -> traveled. Only the forms that double the l in British and not
    # in American; "cancellation", "excelled", "controlled" are American too.
    "-ll": (
        (
            ("led", "ed"),
            ("ling", "ing"),
            ("ler", "er"),
            ("lers", "ers"),
            ("lings", "ings"),
            ("lor", "or"),
            ("lors", "ors"),
            ("lous", "ous"),
            ("lously", "ously"),
            ("lery", "ry"),
            ("list", "ist"),
            ("lists", "ists"),
        ),
        ("", "re", "un", "mis"),
        (
            "cancel",
            "channel",
            "counsel",
            "dial",
            "duel",
            "enamel",
            "equal",
            "fuel",
            "funnel",
            "initial",
            "jewel",
            "label",
            "level",
            "libel",
            "marvel",
            "model",
            "panel",
            "pedal",
            "quarrel",
            "ravel",
            "revel",
            "rival",
            "shovel",
            "signal",
            "snorkel",
            "spiral",
            "stencil",
            "swivel",
            "total",
            "towel",
            "travel",
            "tunnel",
            "yodel",
        ),
    ),
}

# Words that belong to no family, each with its own inflections spelled out. No
# entry here may also be generated by a family or by MEDICAL: the tests check
# that, so every entry is load-bearing.
EXPLICIT: dict[str, str] = {
    "catalogue": "catalog",
    "catalogues": "catalogs",
    "catalogued": "cataloged",
    "cataloguing": "cataloging",
    "cataloguer": "cataloger",
    "cataloguers": "catalogers",
    "grey": "gray",
    "greys": "grays",
    "greyed": "grayed",
    "greying": "graying",
    "greyer": "grayer",
    "greyest": "grayest",
    "greyish": "grayish",
    "greyness": "grayness",
    "greyscale": "grayscale",
    "fulfil": "fulfill",
    "fulfils": "fulfills",
    "fulfilment": "fulfillment",
    "fulfilments": "fulfillments",
    "enrol": "enroll",
    "enrols": "enrolls",
    "enrolment": "enrollment",
    "enrolments": "enrollments",
    "instal": "install",
    "instals": "installs",
    "instalment": "installment",
    "instalments": "installments",
    "instil": "instill",
    "instils": "instills",
    # Only the forms the American spelling does not share: "appalled",
    # "appalling", "enthralled", "distilled" are American too.
    "appal": "appall",
    "appals": "appalls",
    "enthral": "enthrall",
    "enthrals": "enthralls",
    "enthralment": "enthrallment",
    "distil": "distill",
    "distils": "distills",
    # British in the doubled l and the -ise together; "tranquillity" is American.
    "tranquillise": "tranquilize",
    "tranquillised": "tranquilized",
    "tranquillises": "tranquilizes",
    "tranquillising": "tranquilizing",
    "tranquilliser": "tranquilizer",
    "tranquillisers": "tranquilizers",
    "skilful": "skillful",
    "skilfully": "skillfully",
    "unskilful": "unskillful",
    "wilful": "willful",
    "wilfully": "willfully",
    "woollen": "woolen",
    "woollens": "woolens",
    "acknowledgement": "acknowledgment",
    "acknowledgements": "acknowledgments",
    "judgement": "judgment",
    "judgements": "judgments",
    "judgemental": "judgmental",
    "misjudgement": "misjudgment",
    "misjudgements": "misjudgments",
    "abridgement": "abridgment",
    "ageing": "aging",
    "learnt": "learned",
    "unlearnt": "unlearned",
    "towards": "toward",
    "amongst": "among",
    "whilst": "while",
    "enquiry": "inquiry",
    "enquiries": "inquiries",
    "programme": "program",
    "programmes": "programs",
    "storey": "story",
    "storeys": "stories",
    "tyre": "tire",
    "tyres": "tires",
    "plough": "plow",
    "ploughs": "plows",
    "ploughed": "plowed",
    "ploughing": "plowing",
    "aluminium": "aluminum",
    "artefact": "artifact",
    "artefacts": "artifacts",
    "draught": "draft",
    "draughts": "drafts",
    "draughty": "drafty",
    "kerb": "curb",
    "kerbs": "curbs",
    # Not in the -re family: "lustring" is a fabric, spelled so in American too.
    "lustre": "luster",
    "lustres": "lusters",
    "manoeuvre": "maneuver",
    "manoeuvres": "maneuvers",
    "manoeuvred": "maneuvered",
    "manoeuvring": "maneuvering",
    "manoeuvrable": "maneuverable",
    "manoeuvrability": "maneuverability",
    "mould": "mold",
    "moulds": "molds",
    "moulded": "molded",
    "moulding": "molding",
    "mouldings": "moldings",
    "mouldy": "moldy",
    "moult": "molt",
    "moults": "molts",
    "moulted": "molted",
    "moulting": "molting",
    "smoulder": "smolder",
    "smoulders": "smolders",
    "smouldered": "smoldered",
    "smouldering": "smoldering",
    "moustache": "mustache",
    "moustaches": "mustaches",
    "practise": "practice",
    "practised": "practiced",
    "practises": "practices",
    "practising": "practicing",
    "sceptic": "skeptic",
    "sceptics": "skeptics",
    "sceptical": "skeptical",
    "sceptically": "skeptically",
    "scepticism": "skepticism",
    "speciality": "specialty",
    "specialities": "specialties",
    "cheque": "check",
    "cheques": "checks",
    "pyjamas": "pajamas",
    "aeroplane": "airplane",
    "aeroplanes": "airplanes",
    "aeon": "eon",
    "aeons": "eons",
    "mediaeval": "medieval",
    "cosy": "cozy",
    "cosier": "cozier",
    "cosiest": "coziest",
    "cosily": "cozily",
    "cosiness": "coziness",
    "liquorice": "licorice",
    "yoghurt": "yogurt",
    "yoghurts": "yogurts",
    # Compounds of -re words, which that family's endings do not make.
    "centrepiece": "centerpiece",
    "centrepieces": "centerpieces",
    "centreline": "centerline",
    "centrelines": "centerlines",
    "fibreoptic": "fiberoptic",
    "fibreoptics": "fiberoptics",
    "fibreglass": "fiberglass",
    "fibrescope": "fiberscope",
    "fibrescopes": "fiberscopes",
    # Built on "sensitise" with a prefix the -ise family does not take.
    "hyposensitise": "hyposensitize",
    "hyposensitised": "hyposensitized",
    "hyposensitisation": "hyposensitization",
    # The unit alone; a word that ends in it ("milligramme") is a shape.
    "gramme": "gram",
    "grammes": "grams",
    # "tumour" is in the -our family; these are built on it with no ending of
    # that family's.
    "tumourigenic": "tumorigenic",
    "tumourigenicity": "tumorigenicity",
    "tumourigenesis": "tumorigenesis",
    "spirochaete": "spirochete",
    "spirochaetes": "spirochetes",
    "neurone": "neuron",
    "neurones": "neurons",
    "caesium": "cesium",
    # The English plural of "paraesthesia", which MEDICAL does not generate: no
    # MEDICAL ending is -ae.
    "paraesthesiae": "paresthesiae",
}

# British medical spellings, as whole words. Each entry is (British stem,
# American stem, endings, prefixes): every prefix + stem + ending is generated,
# and matched only as an entire word. An ending is a string both spellings
# share, or a (British, American) pair where the ending is British too
# ("anaesthetise"). The endings are a closed set of English ones: none is a
# Latin ending such as -alis, -ium, -icus, -ica or -ae, so a species epithet
# ("faecalis", "faecium", "gonorrhoeae") is never listed. A genus that is also
# an English word ("Oestrus") is capitalized, and a capitalized word is
# reported but never rewritten by --fix (see left_by()).
#
# This is a list, so a British word whose stem is not here is not listed
# ("leucoplakia"); a shape may still find it, and one no shape finds passes
# ("haem" alone, "paeony"). Add the stem, its endings and its prefixes when one
# turns up; the tests demand every stem has a row, with each of its prefixes.
Ending = str | tuple[str, str]
Medical = tuple[str, str, tuple[Ending, ...], tuple[str, ...]]
AEMIA: tuple[Ending, ...] = ("ia", "ias", "ic")
PNOEA: tuple[Ending, ...] = ("a", "as", "ic")
MEDICAL: tuple[Medical, ...] = (
    (
        "haemorrhag",
        "hemorrhag",
        ("e", "es", "ed", "ing", "ic"),
        ("", "non", "post", "pre", "peri"),
    ),
    ("haemorrhoid", "hemorrhoid", ("", "s", "al", "ectomy", "ectomies"), ("",)),
    (
        "haemat",
        "hemat",
        (
            "oma",
            "omas",
            "omata",
            "ology",
            "ological",
            "ologic",
            "ologist",
            "ologists",
            "uria",
            "ocrit",
            "ocrits",
            "emesis",
            "ochezia",
            "opoiesis",
            "opoietic",
        ),
        ("", "micro", "macro"),
    ),
    (
        "haemoly",
        "hemoly",
        ("sis", "tic", "sin", "sins", ("se", "ze"), ("sed", "zed"), ("sing", "zing")),
        ("", "non"),
    ),
    (
        "haemoglobin",
        "hemoglobin",
        ("", "s", "uria", "opathy", "opathies", ("aemia", "emia")),
        ("",),
    ),
    ("haemodialys", "hemodialys", ("is", "es", ("er", "zer"), ("ers", "zers")), ("",)),
    ("haemodynamic", "hemodynamic", ("", "s", "ally"), ("",)),
    ("haemophil", "hemophil", ("ia", "iac", "iacs", "ic"), ("",)),
    ("haemosta", "hemosta", ("sis", "tic", "tics", "t", "ts"), ("",)),
    ("haemopty", "hemopty", ("sis",), ("",)),
    ("haemothorax", "hemothorax", ("", "es"), ("",)),
    ("haemangiom", "hemangiom", ("a", "as", "ata"), ("",)),
    ("haemochromatos", "hemochromatos", ("is",), ("",)),
    ("haemarthros", "hemarthros", ("is", "es"), ("",)),
    ("haemal", "hemal", ("",), ("",)),
    (
        "oedem",
        "edem",
        ("a", "as", "ata", "atous"),
        ("", "non", "myx", "lymph", "angio", "papill", "pseudopapill", "lip"),
    ),
    (
        "oesophag",
        "esophag",
        (
            "us",
            "i",
            "eal",
            "itis",
            "ectomy",
            "ectomies",
            "oscopy",
            "oscopies",
            "ostomy",
        ),
        ("", "gastro", "trans"),
    ),
    (
        "oestr",
        "estr",
        (
            "ogen",
            "ogens",
            "ogenic",
            "ogenicity",
            "adiol",
            "iol",
            "one",
            "us",
            "ous",
        ),
        ("", "anti", "an", "di", "pro", "met", "xeno", "ethinyl"),
    ),
    ("foet", "fet", ("us", "uses", "al", "icide", "oscopy", "id"), ("",)),
    ("faec", "fec", ("es", "al", "aloma", "alith", "aliths"), ("",)),
    ("gynaecolog", "gynecolog", ("y", "ic", "ical", "ist", "ists"), ("", "uro")),
    ("gynaecomasti", "gynecomasti", ("a",), ("",)),
    ("anaem", "anem", AEMIA, ("", "non")),
    ("leukaem", "leukem", (*AEMIA, "ogenesis", "ogenic"), ("", "pre")),
    ("leucaem", "leukem", AEMIA, ("",)),
    ("septicaem", "septicem", AEMIA, ("",)),
    ("ischaem", "ischem", AEMIA, ("", "non")),
    ("glycaem", "glycem", AEMIA, ("", "hypo", "hyper", "normo", "eu")),
    ("bacteraem", "bacterem", AEMIA, ("",)),
    ("viraem", "virem", AEMIA, ("",)),
    ("toxaem", "toxem", AEMIA, ("",)),
    ("uraem", "urem", AEMIA, ("",)),
    ("pyaem", "pyem", AEMIA, ("",)),
    ("hyperaem", "hyperem", AEMIA, ("",)),
    ("thalassaem", "thalassem", AEMIA, ("",)),
    ("oxaem", "oxem", AEMIA, ("hyp", "hyper")),
    ("kalaem", "kalem", AEMIA, ("hypo", "hyper", "normo")),
    ("natraem", "natrem", AEMIA, ("hypo", "hyper", "normo", "eu")),
    ("calcaem", "calcem", AEMIA, ("hypo", "hyper", "normo")),
    ("volaem", "volem", AEMIA, ("hypo", "hyper", "normo", "eu")),
    ("lipidaem", "lipidem", AEMIA, ("hyper", "dys")),
    ("cholesterolaem", "cholesterolem", AEMIA, ("hyper",)),
    ("uricaem", "uricem", AEMIA, ("hypo", "hyper")),
    ("insulinaem", "insulinem", AEMIA, ("hypo", "hyper")),
    ("phosphataem", "phosphatem", AEMIA, ("hypo", "hyper")),
    ("magnesaem", "magnesem", AEMIA, ("hypo", "hyper")),
    ("proteinaem", "proteinem", AEMIA, ("hypo", "hyper", "dys", "para")),
    ("cythaem", "cythem", AEMIA, ("poly",)),
    (
        "anaesthe",
        "anesthe",
        (
            "sia",
            "sias",
            "tic",
            "tics",
            "tist",
            "tists",
            "tically",
            "siology",
            "siologist",
            "siologists",
            "tize",
            "tized",
            "tizing",
            ("tise", "tize"),
            ("tised", "tized"),
            ("tises", "tizes"),
            ("tising", "tizing"),
            ("tisation", "tization"),
        ),
        ("", "non"),
    ),
    ("paraesthesi", "paresthesi", ("a", "as"), ("",)),
    ("dysaesthesi", "dysesthesi", ("a", "as"), ("",)),
    ("synaesthesi", "synesthesi", ("a", "as"), ("",)),
    ("hyperaesthesi", "hyperesthesi", ("a",), ("",)),
    ("hypoaesthesi", "hypoesthesi", ("a",), ("",)),
    ("hypaesthesi", "hypesthesi", ("a",), ("",)),
    ("kinaesthe", "kinesthe", ("sia", "tic"), ("",)),
    ("diarrhoe", "diarrhe", ("a", "as", "al", "ic"), ("",)),
    ("gonorrhoe", "gonorrhe", ("a", "al"), ("",)),
    ("menorrhoe", "menorrhe", ("a",), ("", "a", "dys", "oligo")),
    ("rhinorrhoe", "rhinorrhe", ("a",), ("",)),
    ("steatorrhoe", "steatorrhe", ("a",), ("",)),
    ("seborrhoe", "seborrhe", ("a", "ic"), ("",)),
    ("galactorrhoe", "galactorrhe", ("a",), ("",)),
    ("pnoe", "pne", PNOEA, ("a", "dys", "hypo", "hyper", "tachy", "brady", "ortho")),
    ("paediatric", "pediatric", ("", "s", "ian", "ians", "ally"), ("", "non")),
    ("orthopaed", "orthoped", ("ic", "ics", "ist", "ists", "ically"), ("",)),
    ("paedophil", "pedophil", ("e", "es", "ia", "iac", "iacs", "ic"), ("",)),
    ("encyclopaedi", "encyclopedi", ("a", "as", "c", "st", "sts"), ("",)),
    ("coeliac", "celiac", ("", "s"), ("", "non")),
    ("palaeontolog", "paleontolog", ("y", "ical", "ist", "ists"), ("",)),
    ("caesar", "cesar", ("ean", "eans", "ian", "ians"), ("",)),
    ("aetiolog", "etiolog", ("y", "ies", "ic", "ical", "ically"), ("",)),
    ("homoeopath", "homeopath", ("y", "ic", "s", "ist", "ists", "ically"), ("",)),
    ("homoeosta", "homeosta", ("sis", "tic"), ("",)),
    ("leucocyt", "leukocyt", ("e", "es", "osis", "ic"), ("",)),
    ("leucopeni", "leukopeni", ("a", "c"), ("",)),
    (
        "sulph",
        "sulf",
        (
            "ur",
            "urs",
            "uric",
            "urous",
            "ate",
            "ates",
            "ated",
            "ide",
            "ides",
            "ite",
            "ites",
            "onamide",
            "onamides",
            "onate",
            "onates",
            "onic",
            "onylurea",
            "onylureas",
            "asalazine",
            "amethoxazole",
            "adiazine",
            "oxide",
            "oxides",
            ("ydryl", "hydryl"),
            "adoxine",
            "apyridine",
            "ation",
            "anilamide",
        ),
        ("", "bi", "di"),
    ),
)


def ending_pair(ending: Ending) -> tuple[str, str]:
    return (ending, ending) if isinstance(ending, str) else ending


def generate(
    families: dict[str, Family],
    explicit: dict[str, str],
    medical: tuple[Medical, ...] = (),
) -> dict[str, str]:
    """Every British form, lowercase, mapped to its American one."""
    out: dict[str, str] = {}
    for endings, prefixes, stems in families.values():
        for stem in stems:
            for prefix in prefixes:
                for ending_b, ending_a in endings:
                    out[prefix + stem + ending_b] = prefix + stem + ending_a
    for stem_b, stem_a, endings, prefixes in medical:
        for prefix in prefixes:
            for ending in endings:
                ending_b, ending_a = ending_pair(ending)
                out[prefix + stem_b + ending_b] = prefix + stem_a + ending_a
    out.update(explicit)
    return out


BRITISH: dict[str, str] = generate(FAMILIES, EXPLICIT, MEDICAL)

# The ligatures, as their two letters. Each is one character, so a word keeps
# its length and its column when it is read this way.
LIGATURES = str.maketrans({"œ": "oe", "æ": "ae"})


def american(word: str) -> str | None:
    """The American spelling of `word`, lowercase, or None if it is not listed.
    Only an entire word is looked up: nothing is matched inside a longer one."""
    return BRITISH.get(word.lower().translate(LIGATURES))


# British spellings found by their shape, not by the list: a lowercase word that
# holds a British medical segment ("methaemoglobin", "acidaemia", "otorrhoeas").
# These are reported, and never suggested in the patch: a shape is a guess, and
# its American form (which the report names) is a guess too. Each pattern is
# searched for in the word, and the match must be shorter than the word, so a
# segment alone ("haem" in a hash or an identifier) is not a shape. Where an
# American word can hold a segment's letters by accident, the pattern is
# narrowed, and the en_US dictionary test holds every pattern to it:
SHAPES = (
    # "haem" inside a word only before "a" or "o": "alphaemission" is not.
    r"^haem|haem(?=[ao])",
    # An oe- segment only at the start or after "a", "i", "o" or "y"
    # ("paraoesophageal", "antioedema", "tracheooesophageal", "polyoestrous"):
    # an American prefix ending in "o" before "edema" or "estrogen" makes the
    # same letters ("videoedema", "phytoestrogen", "shoestring").
    r"(?:^|(?<=[aioy]))(?:oedem|oesophag|oestr)",
    # "foet" only before an English ending: "infoetl" is not.
    r"foet(?=al|us|id|o|icid)",
    r"faec",
    r"caec",
    r"paed",
    # Only after the medical prefixes: "aesthetic", "nonaesthetic" and
    # "antiaesthetic" are American. Every British "anaes-" word holds "anaesthe"
    # ("anaesthesia", "unanaesthetised").
    r"(?:an|kin|syn|par|dys|hyper|hypo|hyp|cen)aesthe",
    r"gynae",
    # Only the British medical stems: "leucocratic", "leucoplast", "leucon"
    # and the rest of American geology and botany keep "leuco".
    r"leuc(?:o(?:cyt|pen|dystroph|tom|trien|poie|encephal|plak|derm)|aem)",
    # The British leukaemia words ("leukaemoid", "leukaemogenic").
    r"leukaem",
    r"aetio",
    r"palaeo",
    r"praecord",
    r"pharmacopoei",
    r"spirochaet",
    r"sulph",
    r"tumour",
    r"rrhoea?",
    r"pnoea?",
    r"aemi[ac]",
    # Only at the end: "programmed" holds "gramme".
    r"litres?$",
    r"grammes?$",
)
SHAPE = re.compile("|".join(SHAPES))
# A word that is all segment and still a shape.
SHAPE_WORDS = ("gynae",)
# American spellings that hold a segment, as parts of words.
SHAPE_EXCEPTIONS = (
    "paedomorph",
    "paedogen",
    "caecilian",
    # Zoology and botany the en_US dictionary lacks: the botfly family, blood
    # parasites, a stomach worm's disease, and the spice.
    "oestrid",
    "haemosporid",
    "haemogregarin",
    "haemonch",
    "asafoetid",
    # Families of insects and parasites, and two parasite diseases.
    "caeciliid",
    "caecid",
    "haemulid",
    "haemadipsid",
    "haemoproteid",
    "oestrosis",
    "oestriasis",
)
# Whole words the en_US dictionary accepts as American spellings: not reported,
# though their derivatives the dictionary does not list ("pharmacopoeial") are.
DICTIONARY_WORDS = ("leucotomy", "leucotomies", "pharmacopoeia", "pharmacopoeias")
# Not "-um", "-ium" or "-ous": "haemoperitoneum", "praecordium" and
# "haematogenous" are English.
LATIN_ENDINGS = ("us", "ae", "ii", "alis", "icus", "ica", "icum", "ensis")
NOT_LATIN = ("ous",)
# Latin epithets whose ending looks English, so LATIN_ENDINGS does not cover
# them. Each is not reported wherever it stands; after its genus, binomial()
# would skip it anyway.
LATIN_EPITHETS = (
    "faecium",
    "haematobium",
    "haemominutum",
    "haemofelis",
    "haemocanis",
    "haemophilum",
    # Endings -ans, -ens and -os that no Latin-ending rule covers.
    "haemolysans",
    "oedematiens",
    "haemobos",
    "caecicola",
)
# A word of the letters a-f alone is hex ("#faecab"), not a word.
HEX = re.compile("[a-f]+")
# The suggestion: each British segment, respelled wherever it is in the word,
# in this order ("haem" before "aemi").
SHAPE_RESPELL = (
    ("oesophag", "esophag"),
    ("haem", "hem"),
    ("oedem", "edem"),
    ("oestr", "estr"),
    ("foet", "fet"),
    ("faec", "fec"),
    ("caec", "cec"),
    ("paed", "ped"),
    ("aesthe", "esthe"),
    ("gynae", "gyne"),
    ("leucaem", "leukem"),
    ("leukaem", "leukem"),
    ("leuco", "leuko"),
    ("aetio", "etio"),
    ("palaeo", "paleo"),
    ("praecord", "precord"),
    ("pharmacopoei", "pharmacopei"),
    ("spirochaet", "spirochet"),
    ("sulph", "sulf"),
    ("tumour", "tumor"),
    ("aemi", "emi"),
    ("rrhoe", "rrhe"),
    ("pnoe", "pne"),
    ("litre", "liter"),
    ("gramme", "gram"),
)


def by_shape(word: str) -> str | None:
    """A suggested American spelling of `word` if its shape is British, or None."""
    if not word.islower():
        return None
    key = word.translate(LIGATURES)
    if key not in SHAPE_WORDS:
        match = SHAPE.search(key)
        if match is None or match.group(0) == key:
            return None
        latin = key.endswith(LATIN_ENDINGS) and not key.endswith(NOT_LATIN)
        if (
            latin
            or key in LATIN_EPITHETS
            or key in DICTIONARY_WORDS
            or any(exception in key for exception in SHAPE_EXCEPTIONS)
            or HEX.fullmatch(key)
        ):
            return None
    for british, respelled in SHAPE_RESPELL:
        key = key.replace(british, respelled)
    return key


# The epithet of a binomial, which is Latin, not English: "Tritrichomonas
# foetus", "T. foetus", "*Schistosoma* *haematobium*". Neither a listed word
# nor a shape is reported there. The epithet must be Latin (see epithet()), and
# the genus must be one of GENERA or a capital and a period. Any other
# capitalized word before it ("Severe", "NHS", "Paediatric") is no genus, so a
# British word after it is reported. An English medical word after a genus is
# reported too: "Staphylococcus bacteraemia" is a bacteremia, not a species.
GENERA = frozenset(
    {
        "Arcanobacterium",
        "Campylobacter",
        "Clostridium",
        "Enterococcus",
        "Haemophilus",
        "Mannheimia",
        "Mycoplasma",
        "Neisseria",
        "Pasteurella",
        "Schistosoma",
        "Staphylococcus",
        "Streptococcus",
        "Tritrichomonas",
    }
)
# "-is" covers "-ensis", and "-i" covers "-ii" and "-ae": no listed word ends in
# "-ae", and a shape ending so is Latin already (LATIN_ENDINGS).
EPITHET_ENDINGS = ("a", "i", "is", "um", "us")
# English medical endings among those Latin ones: -ia (every -aemia word, and
# -paedia), -oea (every -rrhoea and -pnoea word), -oma, -itis, and -sis (-osis,
# -ysis, -esis). A word ending so is English, not an epithet. An -ensis epithet
# is never a hit at all: no listed word ends so, and LATIN_ENDINGS keeps it from
# being a shape.
ENGLISH_FORM = re.compile(r"(?:ia|oea|oma|itis|sis)$")
# English nouns that end in a Latin-looking -um or -a, never epithets, so they
# are reported after any genus ("Clostridium caecum perforation"). A true
# epithet that ends so ("faecium", "haematobium", "haemophilum") is skipped.
NOT_EPITHETS = (
    "caecum",
    "haemoperitoneum",
    "haemopericardium",
    "haematometra",
    "praecordium",
)
# A listed word is English, so never an epithet, except these, which are also
# species epithets ("Tritrichomonas foetus", "Campylobacter fetus" written the
# British way).
LISTED_EPITHETS = ("foetus",)
# Markup between a genus and its epithet: an HTML tag or a non-breaking space.
MARKUP = re.compile(r"<[^>]*>|&nbsp;")
# The genus at the end of the text before an epithet, past emphasis, quotes and
# brackets: a name (group 1) or an abbreviation (group 2). An abbreviation is
# one capital letter and a period, and the letter stands at the start of the
# text or directly after whitespace, "*", "_", a quote or an opening bracket:
# "UK." and "Fig. 2A." are none.
GENUS = re.compile(
    r"(?:(?<![A-Za-z])([A-Z][a-z]+)|(?<![^\s*_\"'(\[])([A-Z])\.)[\s*_\"'()\[\]]*$"
)
# The word before an abbreviated genus, past its period and markup.
BEFORE_INITIAL = re.compile(r"([A-Za-z]+)\.?[\s*_\"'()\[\]]*$")
# Words that stand before a capital letter and a period that is no genus: a
# title, or a thing with a letter for a name ("Twin A. foetus", "Hep B.",
# "Appendix B.", "Group A."). Compared in lowercase. The closed list is the
# rule: any other word before the initial leaves it a genus.
NOT_GENUS_WORDS = frozenset(
    {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "hep",
        "group",
        "twin",
        "fig",
        "figure",
        "bed",
        "lead",
        "vitamin",
        "appendix",
        "table",
        "type",
        "grade",
        "stage",
        "class",
        "factor",
        "hepatitis",
        "genotype",
    }
)


def epithet(key: str) -> bool:
    """Whether `key`, a lowercase word, can be a Latin epithet: it ends in a
    Latin form (EPITHET_ENDINGS, but not -ous), not in an English medical one
    (ENGLISH_FORM), and it is not a listed word, but for LISTED_EPITHETS."""
    if not key.endswith(EPITHET_ENDINGS) or key.endswith(NOT_LATIN):
        return False
    if ENGLISH_FORM.search(key) or key in NOT_EPITHETS:
        return False
    return key not in BRITISH or key in LISTED_EPITHETS


def binomial(word: str, before: str, previous: str) -> bool:
    """Whether `word` is the epithet of a binomial: it is lowercase and Latin
    (epithet()), and `before` (the text before it on its line) ends in its
    genus. If nothing but markup is before it, the genus may end `previous`, the
    line before (empty after a blank line)."""
    key = word.translate(LIGATURES)
    if not word.islower() or not epithet(key):
        return False
    text = MARKUP.sub(" ", before)
    if not re.search(r"[A-Za-z0-9]", text):
        text = MARKUP.sub(" ", previous) + " " + text
    genus = GENUS.search(text)
    if genus is None:
        return False
    if genus.group(2) is None:
        return genus.group(1) in GENERA
    titled = BEFORE_INITIAL.search(text[: genus.start()])
    return titled is None or titled.group(1).lower() not in NOT_GENUS_WORDS


MARKER = "spelling-ok"
# A run of letters, any letters: "décentre" is one run, and "réanalyse" another.
LETTERS = re.compile(r"[^\W\d_]+")
# The letters of an English word. A run with any other letter in it (an accent)
# is not English, and is not read: "décentre" is French, not "centre".
ENGLISH = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZœæŒÆ")
# A word, as the checker sees one: within a run of letters, split where an
# identifier changes case, so `colourPicker`, `MAX_COLOURS` and `data-colour-id`
# are each read as their words. Underscores, digits and hyphens separate words.
WORD = re.compile(r"[A-ZŒÆ]+(?![a-zœæ])|[A-ZŒÆ]?[a-zœæ]+")
# The whole run of letters, without splitting identifiers (kept for the tests'
# mutation that shows the split matters).
WHOLE = re.compile(r"[A-Za-zŒÆœæ]+")

# Text that is not prose, and is blanked before the scan, so it is neither
# reported nor rewritten: whatever is spelled there is someone else's, or is
# not a word at all. Each is replaced by spaces of its length, so columns hold.
#
# A URL: a scheme and "://", or one of the schemes written without slashes. The
# scheme starts after a character that is not a letter or digit, so a URL in
# Markdown italics ("_ws://host/x_") is one, and "metadata:" is not "data:". A
# colon alone is not one ("note:colour" is prose).
SCHEMES = (
    "mailto",
    "urn",
    "doi",
    "data",
    "tel",
    "sms",
    "news",
    "blob",
    "javascript",
    "about",
    "geo",
    "magnet",
    "cid",
    "mid",
    "pmid",
    "arxiv",
    "isbn",
)
URL = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z][\w+.-]*://\S+"
    rf"|(?<![A-Za-z0-9])(?:{'|'.join(SCHEMES)}):\S+",
    re.IGNORECASE,
)
# An email address, and the user@host:path form of git.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?::\S*)?")
# A domain, by its top-level domain, with any path after it.
TLDS = (
    "com",
    "org",
    "net",
    "edu",
    "gov",
    "mil",
    "int",
    "io",
    "ai",
    "app",
    "dev",
    "co",
    "uk",
    "us",
    "ca",
    "au",
    "nz",
    "ie",
    "de",
    "fr",
    "eu",
    "nl",
    "info",
    "biz",
    "me",
    "ly",
    "gl",
)
DOMAIN = re.compile(
    rf"\b(?:[A-Za-z0-9-]+\.)+(?:{'|'.join(TLDS)})\b(?:[/:?#][^\s)\]>\"'`]*)?",
)
# A file name with a known extension ("colour.md", "behaviour.json").
FILE_NAME = re.compile(
    r"\b[\w.-]*\w\.(?:md|txt|py|pyi|js|mjs|cjs|ts|tsx|jsx|json|ya?ml|toml"
    r"|html?|css|scss|csv|tsv|png|jpe?g|gif|svg|webp|ico|pdf|sh|bash|git|sql"
    r"|xml|ini|cfg|conf|lock|log|rst|docx?|xlsx?|pptx?|gz|zip|tar|woff2?|ttf"
    r"|otf|env|caddy)\b",
    re.IGNORECASE,
)
# A run with a slash is a path only if it starts with "./", "../", "~/" or "/",
# or a segment has a file extension: "colour/flavour" is prose. A run is matched
# from its first character (a match starts at the leftmost place it can, and
# every character a run is made of can start one), so no lookbehind is needed.
SLASHED = re.compile(r"[\w.~-]*/[\w./~-]*")
EXTENSION = re.compile(r"\w\.[A-Za-z0-9]+$")
# An abbreviation written with dots ("e.g", "i.e", once a trailing period is
# dropped) is not a file name with an extension: "oedema/e.g. swelling" is prose.
DOTTED = re.compile(r"(?:[A-Za-z]\.)+[A-Za-z]")
# A digest named by its algorithm (an SRI hash, a Docker digest).
DIGEST = re.compile(r"\b(?:sha1|sha224|sha256|sha384|sha512|md5)[-:]\S+", re.I)
# Hex needs no pattern: a word is a run of letters, so "#faec00" or a hash is
# read as its runs of the letters a-f, and no British word is spelled with
# those letters alone (the tests check every one).
# A run of the base64 alphabet (and base64url, and the dots of a JWT).
ENCODED = re.compile(r"[A-Za-z0-9+/=_.-]{16,}")


def blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def blank_path(match: re.Match[str]) -> str:
    run = match.group(0)
    path = run.rstrip(".")
    if path.startswith(("./", "../", "~/", "/")) or any(
        EXTENSION.search(segment) and not DOTTED.fullmatch(segment)
        for segment in path.split("/")
    ):
        return " " * len(run)
    return run


def looks_encoded(run: str) -> bool:
    """Whether a long run of the base64 alphabet is data, not words: it ends in
    "=" padding, or it holds a digit and its letters and digits fall into runs
    of one kind (upper case, lower case, digits) two characters long or less on
    average. An identifier's words make longer runs: `renderColourPanelV2Layout`
    averages nearly three. One with no digit is never data, however its case
    changes (`TestWhoSignedAndWhen`)."""
    if run.endswith("="):
        return True
    alnum = [c for c in run if c.isalnum()]
    if not any(c.isdigit() for c in alnum):
        return False

    def kind(c: str) -> int:
        return 0 if c.isdigit() else 1 if c.isupper() else 2

    runs = 1 + sum(kind(a) != kind(b) for a, b in pairwise(alnum))
    return runs * 2 >= len(alnum)


def blank_encoded(match: re.Match[str]) -> str:
    run = match.group(0)
    return " " * len(run) if looks_encoded(run) else run


def blank_unprose(line: str) -> str:
    """Blank what is not prose: URLs, email addresses, domains, file names,
    paths, digests and encoded data."""
    for pattern in (URL, EMAIL, DIGEST, DOMAIN):
        line = pattern.sub(blank, line)
    # A path before a file name, so the file name does not cut the path short.
    line = SLASHED.sub(blank_path, line)
    line = FILE_NAME.sub(blank, line)
    return ENCODED.sub(blank_encoded, line)


def american_for(word: str, american: str) -> str:
    """The American spelling, in the case the British one was written in."""
    if word.isupper() and len(word) > 1:
        return american.upper()
    if word[0].isupper():
        return american[0].upper() + american[1:]
    return american


# A word found: (column, British word, American word, whether it is listed). A
# word that is not listed was found by its shape (by_shape()).
Found = tuple[int, str, str, bool]


def find(line: str, allow: list[str]) -> list[Found]:
    """Each British word in one line.

    `allow` is the phrases allowed in this file. A line with the marker is
    exempt. An allowed phrase exempts only itself, matched exactly: it is blanked
    out before the scan, like a URL, so a British word elsewhere on the same line
    is still caught.
    """
    if MARKER in line:
        return []
    scannable = line
    for phrase in allow:
        scannable = scannable.replace(phrase, " " * len(phrase))
    scannable = blank_unprose(scannable)
    found = []
    for run in LETTERS.finditer(scannable):
        if not ENGLISH.issuperset(run.group(0)):
            continue
        for match in WORD.finditer(scannable, run.start(), run.end()):
            word = match.group(0)
            respelled = american(word)
            listed = respelled is not None
            if not listed:
                respelled = by_shape(word)
            if respelled is not None:
                found.append(
                    (match.start(), word, american_for(word, respelled), listed)
                )
    return found


# Why a hit is not suggested in the --fix patch. It is suggested only when every
# one of these is false, and the report names the first that is true, so a
# person knows why it is theirs to fix. Nothing is written either way: the
# patch is for a person to review, so these only keep the obvious misreadings
# out of it.
class Left(StrEnum):
    SHAPE = "found by its shape, not listed, so its respelling is a guess"
    CAPITALIZED = "capitalized, so it may be a name"
    NOT_PROSE = (
        "not prose: the patch suggests only in .md, .txt and .rst files and the "
        "values of app/i18n/en.json"
    )
    CODE = "in code"
    JOINED = "joined to other text, so it may be part of a name, a path or code"


# The kinds of file the patch suggests in, by suffix; every other file is
# reported only. app/i18n/en.json is prose in its values (CATALOG).
class Kind(StrEnum):
    MARKDOWN = "markdown"
    RST = "rst"
    TEXT = "text"
    CATALOG = "catalog"
    OTHER = "other"


PROSE_SUFFIXES = {".md": Kind.MARKDOWN, ".rst": Kind.RST, ".txt": Kind.TEXT}
CATALOG = f"app/i18n/{Locale.EN}.json"
# The whole line, `"key": "value",`; the value is group 1.
CATALOG_VALUE = re.compile(r'^\s*"(?:[^"\\]|\\.)*"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$')

# What may stand next to a word the patch suggests, between it and the whitespace
# (or the start or end of the line) around it. Before: an opening bracket, a
# quotation mark or Markdown's asterisk. After: those that close, and the
# sentence's punctuation, "." and ":" among them. Nothing else: a letter
# (accented ones too), a digit, "_", "-", "/", "@", "=", "<", "`", "~", "#",
# "$", "%", "&", "+", "\\", "^", "{", "|", "}" or ">", and "." or ":" before
# the word, each mean it is joined to something that may not be prose:
# `task.cancelled()`, `@behaviour`, `GBIF:Oestrus_ovis`, `_colour_`,
# `scale_colour_manual`, `colour-science`, `aes(colour=x)`, `Sulphur8`.
BEFORE = frozenset("([\"'*")
AFTER = frozenset(")]\"'*,;:.!?")
# The text from the last whitespace to a position, and from a position to the
# next whitespace.
LEAD = re.compile(r"\S*$")
TRAIL = re.compile(r"\S*")

# Code, in a prose file. A Markdown fence (``` or ~~~) opens and closes a block;
# a Markdown line indented four spaces or a tab is code; a reStructuredText
# paragraph ending in "::", or a code directive, opens a literal block of the
# lines indented further; and in any prose file, text between backticks is code,
# and so is a line that reads as a command or an import.
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
INDENTED = re.compile(r"(?: {4}|\t)")
RST_CODE = re.compile(r"\s*\.\. (?:code-block|code|sourcecode)::")
INLINE_CODE = re.compile(r"(`+).+?\1")
CODE_LINE = re.compile(
    r"\s*(?:[-*+>]\s+)*(?:import\s|from\s+\S+\s+import\s|\$\s|>>>\s|\.\.\.\s)"
)

# Words after which a word is a module's name, not prose: "import colour".
CODE_WORDS = frozenset({"import", "require", "library"})


class Code:
    """Where code is in a prose file, read line by line, in order."""

    def __init__(self, kind: Kind) -> None:
        self.kind = kind
        self.fence = ""
        # The indent of the line that opened a reStructuredText literal block.
        self.literal: int | None = None

    def whole_line(self, line: str) -> bool:
        """Whether `line`, the next line of the file, is code throughout."""
        if self.kind is Kind.MARKDOWN:
            fence = FENCE.match(line)
            if self.fence:
                mark = fence.group(1) if fence else ""
                if mark[:1] == self.fence[:1] and len(mark) >= len(self.fence):
                    self.fence = ""
                return True
            if fence:
                self.fence = fence.group(1)
                return True
            return bool(INDENTED.match(line))
        if self.kind is Kind.RST:
            indent = len(line) - len(line.lstrip())
            if self.literal is not None:
                if not line.strip() or indent > self.literal:
                    return True
                self.literal = None
            directive = bool(RST_CODE.match(line))
            if directive or line.rstrip().endswith("::"):
                self.literal = indent
            return directive
        return False


def lead_of(line: str, start: int) -> str:
    """What stands between column `start` and the whitespace before it."""
    return LEAD.search(line[:start]).group(0)


def word_before(line: str, start: int) -> str:
    """The whitespace-separated word before the one at column `start` on its
    line, or "" if it is first on its line."""
    before = line[: start - len(lead_of(line, start))].split()
    return before[-1] if before else ""


def in_code(line: str, start: int) -> bool:
    """Whether column `start` of a line of prose is code: the line reads as a
    command or an import, or the column is between backticks."""
    if CODE_LINE.match(line):
        return True
    spans = INLINE_CODE.finditer(line)
    return any(span.start() <= start < span.end() for span in spans)


def left_by(line: str, found: Found, kind: Kind, code: bool) -> Left | None:
    """Why the --fix patch does not suggest `found` in `line`, or None if it does.

    It suggests a word only when the word is listed (not found by its shape), is
    all lowercase, is in a prose file (Markdown, reStructuredText, plain text) or
    a value of the English catalog, is not in code, and stands alone between
    whitespace with only BEFORE before it and AFTER after it. `code` says the
    line is code throughout.
    """
    start, word, _, listed = found
    end = start + len(word)
    if not listed:
        return Left.SHAPE
    if not word.islower():
        return Left.CAPITALIZED
    if kind is Kind.OTHER:
        return Left.NOT_PROSE
    if kind is Kind.CATALOG:
        value = CATALOG_VALUE.match(line)
        if not value or not value.start(1) <= start < end <= value.end(1):
            return Left.NOT_PROSE
    elif code or in_code(line, start):
        return Left.CODE
    lead = lead_of(line, start)
    trail = TRAIL.match(line, end).group(0)
    if not BEFORE.issuperset(lead) or not AFTER.issuperset(trail):
        return Left.JOINED
    if word_before(line, start).strip("([\"'*") in CODE_WORDS:
        return Left.CODE
    return None


# A hit: (column, British word, American word, why the patch leaves it or None).
Hit = tuple[int, str, str, Left | None]


def kind_of(path: Path) -> Kind:
    if relative(path) == CATALOG:
        return Kind.CATALOG
    return PROSE_SUFFIXES.get(path.suffix.lower(), Kind.OTHER)


def hits(path: Path, text: str, allow: list[Allow]) -> list[tuple[int, str, list[Hit]]]:
    """Each line of `text`, the text of `path`, with its hits: (line number, the
    line with its ending, hits). Every listed word and every shape is a hit,
    whatever stands before it, except the epithet of a binomial."""
    kind = kind_of(path)
    phrases = allowed_in(path, allow)
    code = Code(kind)
    previous = ""
    out = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        whole = code.whole_line(line)
        line_hits = [
            (found[0], found[1], found[2], left_by(line, found, kind, whole))
            for found in find(line, phrases)
            if not binomial(found[1], line[: found[0]], previous)
        ]
        out.append((number, line, line_hits))
        previous = line
    return out


def relative(path: Path) -> str:
    """The path from the repository root, or the whole path if it is outside."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def is_translation(rel: str) -> bool:
    """A message catalog in another language (#80). American English is the source
    language, app/i18n/en.json, which IS checked. "Organisation" is correct German and
    "centre" correct French, so judging a translation by English spelling is wrong."""
    parts = Path(rel).parts
    # app/i18n/<tag>.json, or the framework content's app/i18n/framework/<tag>.json.
    if parts[:3] == ("app", "i18n", "framework"):
        parts = ("app", "i18n", *parts[3:])
    return (
        len(parts) == 3
        and parts[:2] == ("app", "i18n")
        and parts[2].endswith(".json")
        and parts[2] != f"{Locale.EN}.json"
    )


def skip(path: Path) -> bool:
    """This file (it IS the word list), the allowlist (it is the list of British
    phrases allowed, so each of its entries is one), anything quoted verbatim,
    the spelling corpus, and translations. pre-commit names files itself, so
    this applies to them."""
    resolved = path.resolve()
    if resolved == SELF:
        return True
    if resolved == ALLOWLIST.resolve():
        return True
    try:
        rel = str(resolved.relative_to(ROOT))
    except ValueError:
        return False
    return (
        rel in QUOTED_VERBATIM
        or PurePosixPath(rel).parent.as_posix() == CORPUS
        or is_translation(rel)
    )


# An allowlist entry: (glob, phrase). The phrase is allowed only in the files
# the glob matches.
Allow = tuple[str, str]


def parse_allowlist(text: str) -> list[Allow]:
    """`glob: phrase` per line. A line with no glob is an error, not a phrase
    allowed everywhere: an exemption names where it applies."""
    entries = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        glob, sep, phrase = line.partition(": ")
        if not sep or not glob or not phrase.strip():
            raise ValueError(
                f"{ALLOWLIST.name}:{number}: expected 'glob: phrase', got {line!r}"
            )
        entries.append((glob, phrase.strip()))
    return entries


def load_allowlist() -> list[Allow]:
    if not ALLOWLIST.exists():
        return []
    return parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))


def allowed_in(path: Path, allow: list[Allow]) -> list[str]:
    """The phrases allowed in `path`."""
    where = PurePosixPath(relative(path))
    return [phrase for glob, phrase in allow if where.match(glob)]


def read(path: Path) -> str:
    """The file's text, its line endings as they are (a patch must match them).
    Raises UnicodeDecodeError or OSError if it cannot be read."""
    return path.read_bytes().decode("utf-8")


# Said of a hit the --fix patch does not suggest, with the reason (a Left).
LEFT_FOR_A_HUMAN = "not in the suggestion patch, so fix it by hand"


def left_note(reason: Left | None) -> str:
    return "" if reason is None else f" ({LEFT_FOR_A_HUMAN}: {reason})"


def check(path: Path, allow: list[Allow]) -> list[str]:
    try:
        text = read(path)
    except UnicodeDecodeError as error:
        return [f"{path}: not valid UTF-8 (byte {error.start}), so not checked"]
    except OSError as error:
        return [f"{path}: could not be read ({error.strerror}), so not checked"]

    problems = []
    for number, line, found in hits(path, text, allow):
        for column, word, respelled, reason in found:
            problems.append(
                f"{path}:{number}:{column + 1}: "
                f"British spelling {word!r} -- use {respelled!r}"
                f"{left_note(reason)}\n"
                f"    {line.strip()[:100]}"
            )
    return problems


def is_text(path: Path) -> bool:
    """Whether pre-commit would call `path` a text file. One that cannot be
    opened counts as text, so check() reports it rather than it being dropped."""
    try:
        with path.open("rb") as handle:
            head = handle.read(1024)
    except OSError:
        return True
    return not head.translate(None, TEXT_BYTES)


def named(argv: list[str]) -> list[Path]:
    """The files named on the command line, each once: two names for one file
    (./a.md and a.md, or a path through a symbolic link to a directory) are one
    file, and a named symbolic link to a file stands for its target (written
    relative to where the command ran if the link was). The first name given
    is kept, so a message names the file as it was written. A link
    to no file is kept as it is, for the caller to say so."""
    seen = set()
    out = []
    for arg in argv:
        path = Path(arg)
        real = Path(os.path.realpath(path))
        if path.is_symlink() and real.is_file():
            path = real if path.is_absolute() else Path(os.path.relpath(real))
        if real not in seen:
            seen.add(real)
            out.append(path)
    return out


def targets(argv: list[str]) -> list[Path]:
    if argv:
        return named(argv)
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and not any(d in SKIP_DIRS for d in p.relative_to(ROOT).parts)
        and is_text(p)
    ]


def suggest(path: Path, allow: list[Allow]) -> tuple[str, str, list[str]]:
    """The text of `path`, the text the suggestion patch would make of it, and
    the hits left for a person (each as "line:column: 'word' -- 'american'
    (why)"). Writes nothing.

    Uses the same scan as check(), so it never suggests what check() does not
    report: an exempt line, an allowed phrase, a URL, an email address, a
    domain, a file name, a path, a digest or encoded data. Of what it reports,
    it suggests only what left_by() allows. A file that cannot be read raises,
    so the caller reports it.
    """
    text = read(path)
    left = []
    out = []
    for number, line, found in hits(path, text, allow):
        # Right to left, so an earlier column is not moved by a later change.
        for column, word, respelled, reason in reversed(found):
            if reason is not None:
                left.append(
                    (number, column, f"{word!r} -- {respelled!r}{left_note(reason)}")
                )
                continue
            line = line[:column] + respelled + line[column + len(word) :]
        out.append(line)
    hand = [f"{n}:{c + 1}: {what}" for n, c, what in sorted(left)]
    return text, "".join(out), hand


# Lines as git reads them: split after each "\n" only, so a form feed or a
# carriage return inside a line stays in it.
GIT_LINE = re.compile(r"[^\n]*\n|[^\n]+$")
NO_NEWLINE = "\\ No newline at end of file\n"


def unified(name: str, before: str, after: str) -> str:
    """A unified diff from `before` to `after`, for the file at `name` (a path
    relative to where `git apply` runs), that `git apply` takes."""
    diff = difflib.unified_diff(
        GIT_LINE.findall(before),
        GIT_LINE.findall(after),
        f"a/{name}",
        f"b/{name}",
    )
    body = "".join(
        line if line.endswith("\n") else f"{line}\n{NO_NEWLINE}" for line in diff
    )
    return f"diff --git a/{name} b/{name}\n{body}"


def patch_name(path: Path) -> str | None:
    """The path the patch names: from the repository root; for a file outside
    it, the path as given, if that is relative and does not climb ("..") so
    `git apply` takes it from where the command ran; otherwise None, because
    `git apply` refuses an absolute path or one that climbs."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        if path.is_absolute() or ".." in path.parts:
            return None
        return path.as_posix()


# Said of a symbolic link named on the command line that points to no file; one
# that points to a file is read as its target (see named()).
SYMLINK = "a symbolic link to no file, so not read"
# Said by --fix of a file it cannot name in a patch.
OUTSIDE = (
    "outside the repository and named by an absolute path or one with '..', "
    "which `git apply` refuses, so its suggestions are not in the patch: name "
    "it relative to a directory above it and run fix-spelling there"
)


PATCH_HEADER = """\
# British spellings: SUGGESTED respellings from `pixi run fix-spelling`.
# This is a suggestion to review, not a fix: nothing has been written. Read
# every hunk (a quotation, a name or code may be among them), drop what is
# wrong, then apply the rest from the repository root with `git apply`.
"""


def main(argv: list[str]) -> int:
    do_fix = "--fix" in argv
    argv = [a for a in argv if a != "--fix"]
    try:
        allow = load_allowlist()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    if do_fix:
        patches = []
        hand = []
        unread = 0
        suggested = 0
        for path in targets(argv):
            if path.is_symlink():
                print(f"  skipped {path}: {SYMLINK}", file=sys.stderr)
                unread += 1
            elif path.is_file() and not skip(path):
                name = patch_name(path)
                try:
                    before, after, left = suggest(path, allow)
                except (UnicodeDecodeError, OSError) as error:
                    print(f"  could not read {path}: {error}", file=sys.stderr)
                    unread += 1
                    continue
                if after != before and name is None:
                    print(f"  {path}: {OUTSIDE}", file=sys.stderr)
                    unread += 1
                elif after != before:
                    patches.append(unified(name, before, after))
                    suggested += 1
                hand.extend(f"  {name or path}:{hit}" for hit in left)
        if patches:
            print(PATCH_HEADER + "".join(patches), end="")
        for line in hand:
            print(line, file=sys.stderr)
        print(
            f"\n{suggested} file(s) with suggestions in the patch on stdout "
            "(review it; nothing was written), "
            f"{len(hand)} hit(s) to fix by hand: respell each, or mark the "
            "line `spelling-ok` if it is a name or a quotation.",
            file=sys.stderr,
        )
        return 1 if unread or patches or hand else 0

    problems = []
    unread = 0
    for path in targets(argv):
        if path.is_symlink():
            print(f"skipped {path}: {SYMLINK}", file=sys.stderr)
            unread += 1
        elif path.is_file() and not skip(path):
            problems.extend(check(path, allow))

    for msg in problems:
        print(msg, file=sys.stderr)

    if unread and not problems:
        return 1
    if problems:
        print(
            f"\n{len(problems)} problem(s) found. This project uses American "
            "English.\nIf a word is quoted from a source, add `spelling-ok` to "
            "the line, or 'glob: phrase' to .spelling-allow.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
