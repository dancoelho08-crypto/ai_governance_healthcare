#!/usr/bin/env python3
"""The British-spelling guard, tested as a guardrail (#169).

scripts/check_spelling.py runs in pre-commit and CI and had no tests, so nothing
showed it failing. It missed a plural in docs/developing.md because only the
singular was listed: a word list of exact forms catches the forms someone
thought to type, and every other inflection of the same root passes in silence.

What is pinned, both ways:

* every word the checker generates, and every word of the table, is caught in
  prose, in a code comment, in a string, and as a part of an identifier
  (snake_case, camelCase, kebab-case), in lower, Title and UPPER case;
* a table written by hand, independently of the checker, is caught with the
  American form it names. It names every EXPLICIT word, a form of every stem,
  ending and prefix of every family, and a form of every MEDICAL stem with
  each of its own prefixes, and the tests demand it does, so dropping any part
  of the checker leaves a row uncaught, or out of the suggestion patch (every
  row is suggested in it); no EXPLICIT word may also be generated, so dropping one
  is always noticed; no MEDICAL form has a Latin ending, and no British word is
  spelled with the letters a-f alone;
* a lowercase word holding a British medical segment anywhere is reported by
  its shape (SHAPED, and the verifier's 131 medical words in
  spelling_corpus/medical.txt), after any capitalized word (the verifier's 132
  sentence openers), and never suggested in the patch; each pattern alone
  catches a word, and each narrowing keeps an American word clean; a
  capitalized word, hex, a Latin ending or epithet, an exception and a word the
  dictionary accepts are not;
* the epithet of a binomial is not reported after a genus in GENERA or an
  abbreviated one (exactly one capital and a period, at the start or after
  whitespace, "*", "_", a quote or an opening bracket, and not after a word of
  NOT_GENUS_WORDS, each of which is pinned), past markup and across a line, and
  is reported after any other word, with an English ending (-ous, -al, and the
  medical -ia, -oea, -oma, -itis, -sis), when it is one of NOT_EPITHETS (each
  pinned), or when it is a listed word other than one of LISTED_EPITHETS;
  LATIN_EPITHETS are not reported wherever they stand; "sulphur" is  # spelling-ok
  reported
  (BINOMIALS has the cases, the verifier's eleven among them);
* no rule matches a lowercase word of the en_US Hunspell dictionary (pinned in
  pixi.toml), read as the checker reads words, except the two in
  CAUGHT_ON_PURPOSE, which CLAUDE.md rules out;
* a British word written with a ligature ("oe" or "ae" as one letter) is caught,
  and a word with an accented letter ("décentre", "réanalyse") is not English
  and is not read;
* American words, and American words a careless new stem would generate
  ("precise", "compelled", "lustring", "improvisation", "leucovorin"), are not
  flagged;
* the verifier's corpus (tests/fixtures/spelling_corpus/): every clean line
  (organisms, drugs, places, titles, names, code, URLs, hex, encoded data, the
  binomial wrapped across lines) produces no finding; no line of names is in
  the suggestion patch; every British line is found, and suggested exactly
  where it may be; Python's own spelling passes in a .py file; and the
  demonstration that the first version corrupted produces no suggestion;
* --fix never writes: no file's bytes or modification time change, for every
  kind of file and for the whole corpus, named or found by a whole-repository
  run. It prints a patch, under a header that says it is a suggestion, that
  `git apply --check` accepts on a copy and that makes exactly the expected
  text (a last line with no newline, CRLF endings, a form feed, the English
  catalog, several files); and it lists the rest for a person;
* the patch suggests a hit only when it is listed, all lowercase, in a
  Markdown, reStructuredText or plain-text file or a value of app/i18n/en.json,
  not in code, and standing alone between whitespace with only an opening
  bracket, a quote or "*" before it and only those that close, "*" or ",;:.!?"
  after it; FIX_CASES pins every boundary character both ways, every kind of
  file, every kind of code, and each of the verifier's cases; the report says,
  of each hit the patch leaves, why;
* the patch never names a file skip() skips; a file named twice (with and
  without "./", through a symbolic link to a directory, or by a link and its
  target) gets one diff that `git apply --check` accepts; a symbolic link to a
  file stands for its target, and a link to no file is said to be skipped and
  exits 1; a file outside the repository named by an absolute path or with ".."
  is refused from the patch, said to be, and exits 1;
* American scientific words the dictionary lacks
  (spelling_corpus/american.txt: "leucocratic", "nonaesthetic", "oestrid",
  "asafoetida" and more) are not reported;
* URLs of every scheme in SCHEMES and domains of every top-level domain in TLDS
  (each list equals one written here, and each entry has a case of its own and
  a mutation), also after "_" and not inside a longer word,
  email and git addresses, domains, file names, paths (with ./, ../, ~/ or /,
  or an extension), digests and encoded data from 16 characters are neither
  reported nor suggested, while an identifier with a digit is still read, and
  an abbreviation with dots ("e.g.") is no file extension;
* `.cancelled()` is exempt only as a method call in a .py file;
* a slash in prose (two words joined by "/") is not a path, while a URL, ./, ../, an
  absolute path and a path with a file extension are; a URL needs "://" or a
  listed scheme, and ends at whitespace; a segment ending in a dot has no
  extension, nor does a dot inside a segment;
* `spelling-ok`, in lowercase, exempts its own line and no other; a
  `.spelling-allow` entry exempts its exact phrase as a whole, in its own case
  (a mixed-case one too), only in the files its glob names, matched against the
  path from the repository root, and an entry with no glob is refused, by
  parse_allowlist() and by the command, which exits 1;
* a file that is not UTF-8, or cannot be read at all, is reported, not passed;
* targets() and skip() read every kind of text file pre-commit would pass (code,
  documentation, .css, .html, .txt, .rst, .svg, a Makefile, a shell script, a
  .caddy file, .env.example, the ignore files, a lock file, a LICENSE) and none
  of our real files is skipped, while a binary file, a symbolic link,
  translations, SKIP_DIRS and QUOTED_VERBATIM (each pinned to exactly its
  entries), the corpus's own files, the allowlist and the checker itself are;
  BEL, BS, VT, FF and ESC bytes are text, a DEL byte is not, only the first
  1024 bytes are read to decide, and a file that cannot be opened counts as
  text;
* the command exits nonzero on a hit, or a file it cannot read, and zero on
  clean input; so does --fix.

Then the checker is broken on purpose, at least once for each property above
(MUTATIONS lists them), and the same assertions must notice. A check never
shown to fail is a claim, not a control. A mutant stops at the first property
that notices it, the fast ones first (noticed()), and the dictionary is
expanded once and handed to every mutant's process, so the run takes well
under a minute on a laptop; the real checker runs every property. One
mutation proposed in review is not here because it changes nothing: removing a
lookbehind from the slash pattern, which matched from the leftmost character
anyway, so the lookbehind was deleted instead. Nor are two others, for the same
reason: "-ensis" and "-ii" were dropped from EPITHET_ENDINGS, which "-is" and
"-i" already cover.

The tests of the in-place rewrite that --fix used to do were deleted with it,
not weakened: what they pinned (where a rewrite may happen) is now pinned as
what the patch suggests.

The British words below are test data, so their lines carry `spelling-ok`.

    pixi run test-check-spelling
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "check_spelling.py"
sys.path.insert(0, str(SCRIPTS))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load(source: str | None = None, name: str = "check_spelling") -> ModuleType:
    """The real checker, or a copy of it built from `source` (a mutant)."""
    path = SCRIPT
    if source is not None:
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "check_spelling.py"
        path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A mutant lives in a temporary directory, so it would take that for the
    # repository root and judge every real path as outside it. Point it home.
    module.ROOT = ROOT
    module.ALLOWLIST = ROOT / ".spelling-allow"
    return module


cs = load()

# ---------------------------------------------------------------------------
# Test data. Each row is "british american"; the trailing marker exempts the
# line from the checker this file is testing. Written by hand, not derived from
# the checker, so it is an independent account of what must be caught.
# ---------------------------------------------------------------------------

TABLE = """
# Every EXPLICIT word, by name. The tests demand this is exactly EXPLICIT, so a
# word dropped from the checker, or added without being written down here, fails.
judgement judgment  spelling-ok
judgements judgments  spelling-ok
judgemental judgmental  spelling-ok
misjudgement misjudgment  spelling-ok
misjudgements misjudgments  spelling-ok
abridgement abridgment  spelling-ok
acknowledgement acknowledgment  spelling-ok
acknowledgements acknowledgments  spelling-ok
catalogue catalog  spelling-ok
catalogues catalogs  spelling-ok
catalogued cataloged  spelling-ok
cataloguing cataloging  spelling-ok
cataloguer cataloger  spelling-ok
cataloguers catalogers  spelling-ok
grey gray  spelling-ok
greys grays  spelling-ok
greyed grayed  spelling-ok
greying graying  spelling-ok
greyer grayer  spelling-ok
greyest grayest  spelling-ok
greyish grayish  spelling-ok
greyness grayness  spelling-ok
greyscale grayscale  spelling-ok
fulfil fulfill  spelling-ok
fulfils fulfills  spelling-ok
fulfilment fulfillment  spelling-ok
fulfilments fulfillments  spelling-ok
enrol enroll  spelling-ok
enrols enrolls  spelling-ok
enrolment enrollment  spelling-ok
enrolments enrollments  spelling-ok
instal install  spelling-ok
instals installs  spelling-ok
instalment installment  spelling-ok
instalments installments  spelling-ok
instil instill  spelling-ok
instils instills  spelling-ok
appal appall  spelling-ok
appals appalls  spelling-ok
enthral enthrall  spelling-ok
enthrals enthralls  spelling-ok
enthralment enthrallment  spelling-ok
distil distill  spelling-ok
distils distills  spelling-ok
tranquillise tranquilize  spelling-ok
tranquillised tranquilized  spelling-ok
tranquillises tranquilizes  spelling-ok
tranquillising tranquilizing  spelling-ok
tranquilliser tranquilizer  spelling-ok
tranquillisers tranquilizers  spelling-ok
skilful skillful  spelling-ok
skilfully skillfully  spelling-ok
unskilful unskillful  spelling-ok
wilful willful  spelling-ok
wilfully willfully  spelling-ok
woollen woolen  spelling-ok
woollens woolens  spelling-ok
ageing aging  spelling-ok
learnt learned  spelling-ok
unlearnt unlearned  spelling-ok
towards toward  spelling-ok
amongst among  spelling-ok
whilst while  spelling-ok
enquiry inquiry  spelling-ok
enquiries inquiries  spelling-ok
programme program  spelling-ok
programmes programs  spelling-ok
storey story  spelling-ok
storeys stories  spelling-ok
tyre tire  spelling-ok
tyres tires  spelling-ok
plough plow  spelling-ok
ploughs plows  spelling-ok
ploughed plowed  spelling-ok
ploughing plowing  spelling-ok
aluminium aluminum  spelling-ok
artefact artifact  spelling-ok
artefacts artifacts  spelling-ok
draught draft  spelling-ok
draughts drafts  spelling-ok
draughty drafty  spelling-ok
kerb curb  spelling-ok
kerbs curbs  spelling-ok
lustre luster  spelling-ok
lustres lusters  spelling-ok
manoeuvre maneuver  spelling-ok
manoeuvres maneuvers  spelling-ok
manoeuvred maneuvered  spelling-ok
manoeuvring maneuvering  spelling-ok
manoeuvrable maneuverable  spelling-ok
manoeuvrability maneuverability  spelling-ok
mould mold  spelling-ok
moulds molds  spelling-ok
moulded molded  spelling-ok
moulding molding  spelling-ok
mouldings moldings  spelling-ok
mouldy moldy  spelling-ok
moult molt  spelling-ok
moults molts  spelling-ok
moulted molted  spelling-ok
moulting molting  spelling-ok
smoulder smolder  spelling-ok
smoulders smolders  spelling-ok
smouldered smoldered  spelling-ok
smouldering smoldering  spelling-ok
moustache mustache  spelling-ok
moustaches mustaches  spelling-ok
practise practice  spelling-ok
practised practiced  spelling-ok
practises practices  spelling-ok
practising practicing  spelling-ok
sceptic skeptic  spelling-ok
sceptics skeptics  spelling-ok
sceptical skeptical  spelling-ok
sceptically skeptically  spelling-ok
scepticism skepticism  spelling-ok
speciality specialty  spelling-ok
specialities specialties  spelling-ok
cheque check  spelling-ok
cheques checks  spelling-ok
pyjamas pajamas  spelling-ok
aeroplane airplane  spelling-ok
aeroplanes airplanes  spelling-ok
aeon eon  spelling-ok
aeons eons  spelling-ok
mediaeval medieval  spelling-ok
cosy cozy  spelling-ok
cosier cozier  spelling-ok
cosiest coziest  spelling-ok
cosily cozily  spelling-ok
cosiness coziness  spelling-ok
liquorice licorice  spelling-ok
yoghurt yogurt  spelling-ok
yoghurts yogurts  spelling-ok
centrepiece centerpiece  spelling-ok
centrepieces centerpieces  spelling-ok
centreline centerline  spelling-ok
centrelines centerlines  spelling-ok
fibreoptic fiberoptic  spelling-ok
fibreoptics fiberoptics  spelling-ok
fibreglass fiberglass  spelling-ok
fibrescope fiberscope  spelling-ok
fibrescopes fiberscopes  spelling-ok
hyposensitise hyposensitize  spelling-ok
hyposensitised hyposensitized  spelling-ok
hyposensitisation hyposensitization  spelling-ok
gramme gram  spelling-ok
grammes grams  spelling-ok
tumourigenic tumorigenic  spelling-ok
tumourigenicity tumorigenicity  spelling-ok
tumourigenesis tumorigenesis  spelling-ok

# -our: a form of every stem, every ending and every prefix.
ardour ardor  spelling-ok
armoured armored  spelling-ok
behaviour behavior  spelling-ok
behaviours behaviors  spelling-ok
behavioural behavioral  spelling-ok
behaviourally behaviorally  spelling-ok
behaviourism behaviorism  spelling-ok
behaviourist behaviorist  spelling-ok
behaviourists behaviorists  spelling-ok
misbehaviour misbehavior  spelling-ok
candour candor  spelling-ok
clamouring clamoring  spelling-ok
colour color  spelling-ok
colourings colorings  spelling-ok
colourful colorful  spelling-ok
colourfulness colorfulness  spelling-ok
colourisation colorization  spelling-ok
colourfully colorfully  spelling-ok
colourless colorless  spelling-ok
colourise colorize  spelling-ok
colourised colorized  spelling-ok
colourising colorizing  spelling-ok
discoloured discolored  spelling-ok
watercolours watercolors  spelling-ok
multicoloured multicolored  spelling-ok
demeanour demeanor  spelling-ok
endeavours endeavors  spelling-ok
endeavoured endeavored  spelling-ok
favoured favored  spelling-ok
favouring favoring  spelling-ok
favourable favorable  spelling-ok
favourably favorably  spelling-ok
unfavourable unfavorable  spelling-ok
favourite favorite  spelling-ok
favourites favorites  spelling-ok
favouritism favoritism  spelling-ok
fervour fervor  spelling-ok
flavours flavors  spelling-ok
harbour harbor  spelling-ok
honoured honored  spelling-ok
honourable honorable  spelling-ok
dishonour dishonor  spelling-ok
humour humor  spelling-ok
humourless humorless  spelling-ok
labourer laborer  spelling-ok
labourers laborers  spelling-ok
laboured labored  spelling-ok
neighbourhood neighborhood  spelling-ok
neighbourhoods neighborhoods  spelling-ok
neighbouring neighboring  spelling-ok
neighbourly neighborly  spelling-ok
neighbourliness neighborliness  spelling-ok
neighbours neighbors  spelling-ok
odours odors  spelling-ok
parlour parlor  spelling-ok
rancour rancor  spelling-ok
rigour rigor  spelling-ok
rumoured rumored  spelling-ok
saviour savior  spelling-ok
savoury savory  spelling-ok
splendour splendor  spelling-ok
succour succor  spelling-ok
tumour tumor  spelling-ok
tumours tumors  spelling-ok
valour valor  spelling-ok
vapours vapors  spelling-ok
vigour vigor  spelling-ok

# -re
calibre caliber  spelling-ok
centre center  spelling-ok
centres centers  spelling-ok
centred centered  spelling-ok
centring centering  spelling-ok
epicentre epicenter  spelling-ok
decentred decentered  spelling-ok
recentred recentered  spelling-ok
fibres fibers  spelling-ok
goitre goiter  spelling-ok
litres liters  spelling-ok
meagre meager  spelling-ok
metres meters  spelling-ok
kilometres kilometers  spelling-ok
centimetre centimeter  spelling-ok
millimetre millimeter  spelling-ok
micrometre micrometer  spelling-ok
nanometre nanometer  spelling-ok
ochre ocher  spelling-ok
sabres sabers  spelling-ok
sceptre scepter  spelling-ok
sombre somber  spelling-ok
spectre specter  spelling-ok
theatres theaters  spelling-ok

# -ce
defence defense  spelling-ok
defences defenses  spelling-ok
defenceless defenseless  spelling-ok
self-defence self-defense  spelling-ok
licences licenses  spelling-ok
licenced licensed  spelling-ok
licencing licensing  spelling-ok
sublicence sublicense  spelling-ok
offences offenses  spelling-ok
pretence pretense  spelling-ok

# -ise
anaesthetise anesthetize  spelling-ok
anaesthetised anesthetized  spelling-ok
anesthetise anesthetize  spelling-ok
anonymised anonymized  spelling-ok
apologised apologized  spelling-ok
authorising authorizing  spelling-ok
unauthorised unauthorized  spelling-ok
preauthorisation preauthorization  spelling-ok
capitalise capitalize  spelling-ok
categorisation categorization  spelling-ok
catheterise catheterize  spelling-ok
catheterisation catheterization  spelling-ok
centralised centralized  spelling-ok
characterisation characterization  spelling-ok
mischaracterised mischaracterized  spelling-ok
civilisation civilization  spelling-ok
colonise colonize  spelling-ok
conceptualise conceptualize  spelling-ok
containerised containerized  spelling-ok
contextualise contextualize  spelling-ok
criticising criticizing  spelling-ok
customised customized  spelling-ok
digitise digitize  spelling-ok
emphasising emphasizing  spelling-ok
overemphasise overemphasize  spelling-ok
energise energize  spelling-ok
equalise equalize  spelling-ok
familiarise familiarize  spelling-ok
fantasise fantasize  spelling-ok
finalised finalized  spelling-ok
formalise formalize  spelling-ok
generalisation generalization  spelling-ok
globalisation globalization  spelling-ok
harmonise harmonize  spelling-ok
hospitalised hospitalized  spelling-ok
hypothesise hypothesize  spelling-ok
idealised idealized  spelling-ok
immunise immunize  spelling-ok
immunisation immunization  spelling-ok
incentivise incentivize  spelling-ok
initialising initializing  spelling-ok
internalise internalize  spelling-ok
itemised itemized  spelling-ok
jeopardise jeopardize  spelling-ok
legalise legalize  spelling-ok
legitimise legitimize  spelling-ok
localisation localization  spelling-ok
marginalised marginalized  spelling-ok
materialise materialize  spelling-ok
maximise maximize  spelling-ok
memorise memorize  spelling-ok
metabolise metabolize  spelling-ok
minimises minimizes  spelling-ok
mobilise mobilize  spelling-ok
modernise modernize  spelling-ok
monetise monetize  spelling-ok
nationalised nationalized  spelling-ok
neutralise neutralize  spelling-ok
normaliser normalizer  spelling-ok
operationalise operationalize  spelling-ok
optimiser optimizer  spelling-ok
optimisers optimizers  spelling-ok
optimisation optimization  spelling-ok
organise organize  spelling-ok
organisational organizational  spelling-ok
organisations organizations  spelling-ok
reorganised reorganized  spelling-ok
disorganised disorganized  spelling-ok
parameterised parameterized  spelling-ok
parametrise parametrize  spelling-ok
patronising patronizing  spelling-ok
penalise penalize  spelling-ok
personalised personalized  spelling-ok
polarisation polarization  spelling-ok
popularise popularize  spelling-ok
prioritising prioritizing  spelling-ok
prioritisation prioritization  spelling-ok
privatise privatize  spelling-ok
pseudonymisation pseudonymization  spelling-ok
publicise publicize  spelling-ok
randomised randomized  spelling-ok
rationalise rationalize  spelling-ok
realising realizing  spelling-ok
realisation realization  spelling-ok
recognising recognizing  spelling-ok
recognisable recognizable  spelling-ok
unrecognised unrecognized  spelling-ok
sanitiser sanitizer  spelling-ok
scrutinise scrutinize  spelling-ok
sensitise sensitize  spelling-ok
alkalinise alkalinize  spelling-ok
alkalinisation alkalinization  spelling-ok
recanalise recanalize  spelling-ok
recanalisation recanalization  spelling-ok
catastrophising catastrophizing  spelling-ok
cicatrisation cicatrization  spelling-ok
dichotomise dichotomize  spelling-ok
dichotomised dichotomized  spelling-ok
externalising externalizing  spelling-ok
feminisation feminization  spelling-ok
hyalinisation hyalinization  spelling-ok
infantilise infantilize  spelling-ok
isomerisation isomerization  spelling-ok
keratinisation keratinization  spelling-ok
luteinise luteinize  spelling-ok
luteinising luteinizing  spelling-ok
luteinisation luteinization  spelling-ok
masculinisation masculinization  spelling-ok
mentalisation mentalization  spelling-ok
pathologise pathologize  spelling-ok
pathologising pathologizing  spelling-ok
regularisation regularization  spelling-ok
somatisation somatization  spelling-ok
somatising somatizing  spelling-ok
virilisation virilization  spelling-ok
virilising virilizing  spelling-ok
devitalised devitalized  spelling-ok
revitalise revitalize  spelling-ok
serialiser serializer  spelling-ok
deserialise deserialize  spelling-ok
deserialised deserialized  spelling-ok
socialise socialize  spelling-ok
specialising specializing  spelling-ok
specialisation specialization  spelling-ok
stabilise stabilize  spelling-ok
standardising standardizing  spelling-ok
nonstandardised nonstandardized  spelling-ok
sterilised sterilized  spelling-ok
subsidise subsidize  spelling-ok
summarises summarizes  spelling-ok
symbolise symbolize  spelling-ok
sympathise sympathize  spelling-ok
synchronise synchronize  spelling-ok
synthesising synthesizing  spelling-ok
theorise theorize  spelling-ok
tokeniser tokenizer  spelling-ok
trivialise trivialize  spelling-ok
utilisation utilization  spelling-ok
underutilised underutilized  spelling-ok
vaporise vaporize  spelling-ok
vascularise vascularize  spelling-ok
vascularisation vascularization  spelling-ok
victimised victimized  spelling-ok
virtualisation virtualization  spelling-ok
visualise visualize  spelling-ok
weaponised weaponized  spelling-ok
traumatise traumatize  spelling-ok
traumatised traumatized  spelling-ok
stigmatise stigmatize  spelling-ok
destigmatise destigmatize  spelling-ok
destigmatisation destigmatization  spelling-ok
fertilise fertilize  spelling-ok
fertilisation fertilization  spelling-ok
fertiliser fertilizer  spelling-ok
ionise ionize  spelling-ok
ionisation ionization  spelling-ok
pasteurise pasteurize  spelling-ok
pasteurisation pasteurization  spelling-ok
nebulise nebulize  spelling-ok
nebuliser nebulizer  spelling-ok
cauterise cauterize  spelling-ok
metastasise metastasize  spelling-ok
metastasised metastasized  spelling-ok
mineralisation mineralization  spelling-ok
demineralisation demineralization  spelling-ok
heparinised heparinized  spelling-ok
lyophilised lyophilized  spelling-ok
homogenise homogenize  spelling-ok
homogenisation homogenization  spelling-ok
oxidise oxidize  spelling-ok
oxidiser oxidizer  spelling-ok
crystallise crystallize  spelling-ok
crystallisation crystallization  spelling-ok
hypnotise hypnotize  spelling-ok
institutionalise institutionalize  spelling-ok
deinstitutionalisation deinstitutionalization  spelling-ok
medicalise medicalize  spelling-ok
medicalisation medicalization  spelling-ok
humanise humanize  spelling-ok
dehumanising dehumanizing  spelling-ok
commercialise commercialize  spelling-ok
commercialisation commercialization  spelling-ok
moisturise moisturize  spelling-ok
moisturiser moisturizer  spelling-ok
pressurise pressurize  spelling-ok
depressurised depressurized  spelling-ok
immobilise immobilize  spelling-ok
immobilisation immobilization  spelling-ok
neovascularisation neovascularization  spelling-ok
hyperpolarisation hyperpolarization  spelling-ok

# -yse
analyse analyze  spelling-ok
analyser analyzer  spelling-ok
analysers analyzers  spelling-ok
analysing analyzing  spelling-ok
reanalysed reanalyzed  spelling-ok
overanalyse overanalyze  spelling-ok
psychoanalyse psychoanalyze  spelling-ok
catalyse catalyze  spelling-ok
cytolysed cytolyzed  spelling-ok
plasmolyse plasmolyze  spelling-ok
thrombolyse thrombolyze  spelling-ok
thrombolysed thrombolyzed  spelling-ok
thrombolysing thrombolyzing  spelling-ok
dialyse dialyze  spelling-ok
electrolyse electrolyze  spelling-ok
hydrolysed hydrolyzed  spelling-ok
paralysed paralyzed  spelling-ok

# -ll
cancelling canceling  spelling-ok
channelled channeled  spelling-ok
counsellor counselor  spelling-ok
counsellors counselors  spelling-ok
dialled dialed  spelling-ok
duelling dueling  spelling-ok
enamelled enameled  spelling-ok
equalled equaled  spelling-ok
fuelling fueling  spelling-ok
funnelled funneled  spelling-ok
initialled initialed  spelling-ok
jeweller jeweler  spelling-ok
jewellery jewelry  spelling-ok
labelled labeled  spelling-ok
labeller labeler  spelling-ok
labellings labelings  spelling-ok
relabelled relabeled  spelling-ok
mislabelled mislabeled  spelling-ok
levelled leveled  spelling-ok
libellous libelous  spelling-ok
marvellous marvelous  spelling-ok
marvellously marvelously  spelling-ok
modelling modeling  spelling-ok
modeller modeler  spelling-ok
modellers modelers  spelling-ok
panellist panelist  spelling-ok
panellists panelists  spelling-ok
pedalling pedaling  spelling-ok
quarrelling quarreling  spelling-ok
unravelled unraveled  spelling-ok
revelling reveling  spelling-ok
rivalled rivaled  spelling-ok
shovelled shoveled  spelling-ok
signalling signaling  spelling-ok
snorkelling snorkeling  spelling-ok
spiralling spiraling  spelling-ok
stencilled stenciled  spelling-ok
swivelled swiveled  spelling-ok
totalled totaled  spelling-ok
towelling toweling  spelling-ok
travellers travelers  spelling-ok
tunnelling tunneling  spelling-ok
yodelling yodeling  spelling-ok

# MEDICAL: a form of every stem and every prefix, and the inflections a list
# of exact forms missed.
haemorrhage hemorrhage  spelling-ok
haemorrhages hemorrhages  spelling-ok
haemorrhagic hemorrhagic  spelling-ok
haematoma hematoma  spelling-ok
haematomas hematomas  spelling-ok
haematocrit hematocrit  spelling-ok
haematuria hematuria  spelling-ok
haematology hematology  spelling-ok
haematologist hematologist  spelling-ok
haemodialysis hemodialysis  spelling-ok
haemodynamic hemodynamic  spelling-ok
haemoglobin hemoglobin  spelling-ok
haemolysis hemolysis  spelling-ok
haemophilia hemophilia  spelling-ok
haemostasis hemostasis  spelling-ok
haemoptysis hemoptysis  spelling-ok
haemorrhoids hemorrhoids  spelling-ok
oedema edema  spelling-ok
oedemas edemas  spelling-ok
oedematous edematous  spelling-ok
oesophagus esophagus  spelling-ok
oesophageal esophageal  spelling-ok
oesophagitis esophagitis  spelling-ok
oestrogen estrogen  spelling-ok
oestradiol estradiol  spelling-ok
foetus fetus  spelling-ok
foetuses fetuses  spelling-ok
foetal fetal  spelling-ok
caesarean cesarean  spelling-ok
caesareans cesareans  spelling-ok
caesarian cesarian  spelling-ok
anaemia anemia  spelling-ok
anaemic anemic  spelling-ok
leukaemia leukemia  spelling-ok
leukaemias leukemias  spelling-ok
septicaemia septicemia  spelling-ok
septicaemic septicemic  spelling-ok
ischaemia ischemia  spelling-ok
ischaemic ischemic  spelling-ok
hypoglycaemia hypoglycemia  spelling-ok
hyperglycaemia hyperglycemia  spelling-ok
glycaemic glycemic  spelling-ok
bacteraemia bacteremia  spelling-ok
toxaemia toxemia  spelling-ok
uraemia uremia  spelling-ok
hypoxaemia hypoxemia  spelling-ok
anaesthesia anesthesia  spelling-ok
anaesthetic anesthetic  spelling-ok
anaesthetist anesthetist  spelling-ok
diarrhoea diarrhea  spelling-ok
diarrhoeal diarrheal  spelling-ok
gonorrhoea gonorrhea  spelling-ok
dyspnoea dyspnea  spelling-ok
dyspnoeic dyspneic  spelling-ok
apnoea apnea  spelling-ok
paediatric pediatric  spelling-ok
paediatrician pediatrician  spelling-ok
orthopaedic orthopedic  spelling-ok
orthopaedist orthopedist  spelling-ok
encyclopaedia encyclopedia  spelling-ok
gynaecology gynecology  spelling-ok
gynaecologic gynecologic  spelling-ok
gynaecologist gynecologist  spelling-ok
coeliac celiac  spelling-ok
noncoeliac nonceliac  spelling-ok
faeces feces  spelling-ok
faecal fecal  spelling-ok
aetiology etiology  spelling-ok
sulphur sulfur  spelling-ok
sulphate sulfate  spelling-ok
sulphuric sulfuric  spelling-ok
homoeopathy homeopathy  spelling-ok
homoeopathic homeopathic  spelling-ok
homoeostasis homeostasis  spelling-ok
leucocyte leukocyte  spelling-ok
leucocytes leukocytes  spelling-ok
leucocytosis leukocytosis  spelling-ok
leucopenia leukopenia  spelling-ok
haemothorax hemothorax  spelling-ok
haemangioma hemangioma  spelling-ok
haemochromatosis hemochromatosis  spelling-ok
haemarthrosis hemarthrosis  spelling-ok
haemal hemal  spelling-ok
haemolysed hemolyzed  spelling-ok
gynaecomastia gynecomastia  spelling-ok
urogynaecology urogynecology  spelling-ok
viraemia viremia  spelling-ok
pyaemia pyemia  spelling-ok
hyperaemia hyperemia  spelling-ok
thalassaemia thalassemia  spelling-ok
hyperoxaemia hyperoxemia  spelling-ok
hypokalaemia hypokalemia  spelling-ok
hyponatraemia hyponatremia  spelling-ok
hypercalcaemia hypercalcemia  spelling-ok
hypovolaemia hypovolemia  spelling-ok
euvolaemia euvolemia  spelling-ok
normoglycaemia normoglycemia  spelling-ok
dyslipidaemia dyslipidemia  spelling-ok
hypercholesterolaemia hypercholesterolemia  spelling-ok
hyperuricaemia hyperuricemia  spelling-ok
hyperinsulinaemia hyperinsulinemia  spelling-ok
hypophosphataemia hypophosphatemia  spelling-ok
hypomagnesaemia hypomagnesemia  spelling-ok
paraproteinaemia paraproteinemia  spelling-ok
polycythaemia polycythemia  spelling-ok
nonanaemic nonanemic  spelling-ok
preleukaemia preleukemia  spelling-ok
paraesthesia paresthesia  spelling-ok
dysaesthesia dysesthesia  spelling-ok
synaesthesia synesthesia  spelling-ok
hyperaesthesia hyperesthesia  spelling-ok
hypoaesthesia hypoesthesia  spelling-ok
kinaesthetic kinesthetic  spelling-ok
amenorrhoea amenorrhea  spelling-ok
dysmenorrhoea dysmenorrhea  spelling-ok
rhinorrhoea rhinorrhea  spelling-ok
steatorrhoea steatorrhea  spelling-ok
seborrhoeic seborrheic  spelling-ok
galactorrhoea galactorrhea  spelling-ok
tachypnoea tachypnea  spelling-ok
bradypnoea bradypnea  spelling-ok
orthopnoea orthopnea  spelling-ok
paedophile pedophile  spelling-ok
myxoedema myxedema  spelling-ok
lymphoedema lymphedema  spelling-ok
angiooedema angioedema  spelling-ok
papilloedema papilledema  spelling-ok
lipoedema lipedema  spelling-ok
pseudopapilloedema pseudopapilledema  spelling-ok
gastrooesophageal gastroesophageal  spelling-ok
transoesophageal transesophageal  spelling-ok
anoestrus anestrus  spelling-ok
dioestrus diestrus  spelling-ok
prooestrus proestrus  spelling-ok
metoestrus metestrus  spelling-ok
antioestrogen antiestrogen  spelling-ok
posthaemorrhagic posthemorrhagic  spelling-ok
perihaemorrhagic perihemorrhagic  spelling-ok
macrohaematuria macrohematuria  spelling-ok
microhaematuria microhematuria  spelling-ok
disulphide disulfide  spelling-ok
bisulphate bisulfate  spelling-ok
# Added after the verifier's third pass (#169).
oesophagi esophagi  spelling-ok
colouration coloration  spelling-ok
discolouration discoloration  spelling-ok
malodour malodor  spelling-ok
decilitre deciliter  spelling-ok
femtolitre femtoliter  spelling-ok
picolitre picoliter  spelling-ok
decimetre decimeter  spelling-ok
titre titer  spelling-ok
titres titers  spelling-ok
epithelialisation epithelialization  spelling-ok
solubilise solubilize  spelling-ok
hybridise hybridize  spelling-ok
polymerisation polymerization  spelling-ok
opsonisation opsonization  spelling-ok
lateralisation lateralization  spelling-ok
aerosolise aerosolize  spelling-ok
autolyse autolyze  spelling-ok
spirochaete spirochete  spelling-ok
spirochaetes spirochetes  spelling-ok
neurone neuron  spelling-ok
neurones neurons  spelling-ok
caesium cesium  spelling-ok
paraesthesiae paresthesiae  spelling-ok
xenooestrogen xenoestrogen  spelling-ok
ethinyloestradiol ethinylestradiol  spelling-ok
foetid fetid  spelling-ok
leucaemia leukemia  spelling-ok
hypaesthesia hypesthesia  spelling-ok
menorrhoea menorrhea  spelling-ok
oligomenorrhoea oligomenorrhea  spelling-ok
palaeontology paleontology  spelling-ok
sulphoxide sulfoxide  spelling-ok
sulphydryl sulfhydryl  spelling-ok
sulphadoxine sulfadoxine  spelling-ok
sulphapyridine sulfapyridine  spelling-ok
sulphation sulfation  spelling-ok
sulphanilamide sulfanilamide  spelling-ok
anaesthetically anesthetically  spelling-ok
# Added after the verifier's seventh pass (#169): closed compounds of the -our
# and -re roots, the "re" prefix of the -our family, and two more endings.
recoloured recolored  spelling-ok
colourblind colorblind  spelling-ok
colourant colorant  spelling-ok
colourants colorants  spelling-ok
colourway colorway  spelling-ok
colourways colorways  spelling-ok
harbourmaster harbormaster  spelling-ok
harbourmasters harbormasters  spelling-ok
flavoursome flavorsome  spelling-ok
centrefold centerfold  spelling-ok
centrefolds centerfolds  spelling-ok
centreboard centerboard  spelling-ok
centreboards centerboards  spelling-ok
fibreboard fiberboard  spelling-ok
theatregoer theatergoer  spelling-ok
theatregoers theatergoers  spelling-ok
leukaemogenesis leukemogenesis  spelling-ok
leukaemogenic leukemogenic  spelling-ok
# A form of every MEDICAL stem with each of its own prefixes.
nonanaesthetic nonanesthetic  spelling-ok
hypocalcaemia hypocalcemia  spelling-ok
normocalcaemia normocalcemia  spelling-ok
euglycaemia euglycemia  spelling-ok
nonhaemolytic nonhemolytic  spelling-ok
nonhaemorrhagic nonhemorrhagic  spelling-ok
prehaemorrhagic prehemorrhagic  spelling-ok
hypoinsulinaemia hypoinsulinemia  spelling-ok
nonischaemic nonischemic  spelling-ok
hyperkalaemia hyperkalemia  spelling-ok
normokalaemia normokalemia  spelling-ok
hyperlipidaemia hyperlipidemia  spelling-ok
hypermagnesaemia hypermagnesemia  spelling-ok
eunatraemia eunatremia  spelling-ok
hypernatraemia hypernatremia  spelling-ok
normonatraemia normonatremia  spelling-ok
nonoedematous nonedematous  spelling-ok
nonpaediatric nonpediatric  spelling-ok
hyperphosphataemia hyperphosphatemia  spelling-ok
hyperpnoea hyperpnea  spelling-ok
hypopnoea hypopnea  spelling-ok
dysproteinaemia dysproteinemia  spelling-ok
hyperproteinaemia hyperproteinemia  spelling-ok
hypoproteinaemia hypoproteinemia  spelling-ok
hypouricaemia hypouricemia  spelling-ok
hypervolaemia hypervolemia  spelling-ok
normovolaemia normovolemia  spelling-ok
"""

# The ligatures, read as their two letters.
LIGATURE_ROWS = [
    ("manœuvre", "maneuver"),  # spelling-ok
    ("œdema", "edema"),  # spelling-ok
    ("fœtus", "fetus"),  # spelling-ok
    ("anæmia", "anemia"),  # spelling-ok
    ("Œdema", "Edema"),  # spelling-ok
    ("MANŒUVRE", "MANEUVER"),  # spelling-ok
]

# American words, and words that merely contain a British string, which the
# checker must leave alone. Several are inflections of an American root that
# look like a British one ("enrolled" holds a British root; "analyses" is the
# plural of "analysis"); several would be generated by a careless new stem
# ("precise" by an -ise stem "prec", "compelled" by a doubled-l stem "compel");
# and several contain a British medical segment's letters ("aerial", "Caesar",
# "Haemophilus"). Some are left out of the checker on purpose (the -ogue words,
# "burnt", "glamour"); the docstring of the checker says why.
AMERICAN = """
enrolled enrolling enrollment installed installing installment installation
installs instill fulfilled fulfilling analyses paralyses programmed programming
programmer cancellation licensed licensee license practices practiced catalog
dialogue analogue monologue prologue epilogue analog colored meter center
theater offense defense pretense behavior organize organization greyhound
Kerberos parameter diameter tour contour devour concentrate excelled
controlled compelled propelled rebelled patrolled advise revise supervised
exercise enterprise compromise surprised televised advertise precise concise
chastise comprise premise expertise acre genre massacre mediocre ogre glamour
specter caliber scepter luster lustring sabotage theatrical fibrous metric
modeled labeled travel signal channel dialed fueled panelist woolen woolly
while among toward judgment acknowledgment specialty skeptical mold molt
smolder plow draft artifact story learned aging ageism inquiry burnt dreamt
spelt rancorous vigorous humorous odorous laborious
aerial aerobic aesthetic archaeology academia Caesar coelacanth coelom
Haemophilus Haemonchus paean onomatopoeia phoenix Oedipus coefficient coed
algae larvae vertebrae formulae maestro Michael Israel amoeba hemorrhage
edema esophagus fetus feces celiac apnea sulfur estrogen pediatric anesthesia
improvisation improvise improvised supervise merchandise franchise demise
otherwise likewise appall appalled appalling enthrall enthralled enthralling
distill distilled distillation tranquillity tranquilize leucovorin leucine
homeopathy eon medieval licorice yogurt cozy cosine ionic ionization humanism
pressure moisture crystalline fertility oxide mineral centerpiece fiberglass
paedomorphosis paedomorphic paedogenesis paedogenetic Caesarea Aemilia Aemilius
"""

# Capitalized British words, which may be names: reported, and not in the
# suggestion patch. Each row is (line, the words reported).
CAPITALIZED = [
    ("Haemorrhage was noted.", ["Haemorrhage"]),  # spelling-ok
    ("Paediatric Care", ["Paediatric"]),  # spelling-ok
    ("See the British Journal of Haematology.", ["Haematology"]),  # spelling-ok
    ("Oestrus ovis, of the family Oestridae.", ["Oestrus"]),  # spelling-ok
    ("Sulphur, Louisiana", ["Sulphur"]),  # spelling-ok
    ("A BEHAVIOUR SHOUT", ["BEHAVIOUR"]),  # spelling-ok
    ("the Lexington-Centre trust", ["Centre"]),  # spelling-ok
    ("ColourPicker", ["Colour"]),  # spelling-ok
    ("An \u0152dema.", ["\u0152dema"]),
    ("Haemonetics Corporation", []),  # spelling-ok
]
# A British word inside an identifier: reported, with its American form, and
# not in the suggestion patch, which never suggests in code (it may be a third
# party's name).
IDENTIFIERS = [
    ("getColourValue()", "Color"),  # spelling-ok
    ("MAX_COLOURS = 3", "COLORS"),  # spelling-ok
    ("COLOUR_MAX = 3", "COLOR"),  # spelling-ok
    ("x = COLOUR2", "COLOR"),  # spelling-ok
    ("renderColourPanelV2Layout()", "Color"),  # spelling-ok
    ("self.colour = 1", "color"),  # spelling-ok
    # Its case changes often, but it has no digit: not taken for encoded data.
    ("TestWhoColouredItAndWhen", "Colored"),  # spelling-ok
    # Short, so not taken for encoded data.
    ("let aColour2 = 0", "Color"),  # spelling-ok
]

# Text that is not prose: never reported, never rewritten.
NOT_PROSE = [
    "mailto:colour",  # spelling-ok
    "MAILTO:colour",  # spelling-ok
    "urn:colour:behaviour",  # spelling-ok
    "doi:colour",  # spelling-ok
    "data:text/plain,colour",  # spelling-ok
    "tel:colour",  # spelling-ok
    "write to colour.team@example.org now",  # spelling-ok
    "git@github.com:org/colour-tools.git",  # spelling-ok
    "www.colour.org",  # spelling-ok
    "see colour.nhs.uk/behaviour today",  # spelling-ok
    "favour.io",  # spelling-ok
    "example.com/x?colour=1",  # spelling-ok
    "clone colour-tools.git",  # spelling-ok
    "git@github.com:colour",  # spelling-ok
    "see colour.md and behaviour.JSON",  # spelling-ok
    # A path with an extension no list names, before a period.
    "See docs/colour.qmd.",  # spelling-ok
    'integrity="sha256-ColourBehaviourFavour"',  # spelling-ok
    "ColourBehaviourHonourFavour1==",  # spelling-ok
    "x QmVoYXZpb3VyIGNvbG91cgAbHaemoglobin",  # spelling-ok
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJoYWVtIn0.HaemFaecPaedSulphxyz",  # spelling-ok
    "#faec00 3faec12 9faec3d1-0000-4000-8000-000000000000",
    # A URL after "_" (Markdown italics), with a scheme or without.
    "_ws://localhost/colour_",  # spelling-ok
    "_ws://host?colour_",  # spelling-ok
    "_mailto:colour_",  # spelling-ok
    "javascript:alert('colour')",  # spelling-ok
    "see behaviour.gov now",  # spelling-ok
    "pin colour.lock today",  # spelling-ok
    "md5:colour",  # spelling-ok
    "~/colour/notes",  # spelling-ok
    "see /users/~colour/notes now",  # spelling-ok
    "pmid:colour",  # spelling-ok
    "see colour.edu now",  # spelling-ok
    "proxy/colour.caddy",  # spelling-ok
    "colour.caddy",  # spelling-ok
]
# Every scheme written without slashes and every top-level domain the checker
# lists, written out by hand: the checker's lists must equal these, so dropping
# one is noticed, and each gets a case of its own (not_prose()).
SCHEMES = [
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
]
TLDS = [
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
]

# Ordinary American lines that must stay clean: URLs and paths among them.
CLEAN = [
    "The organization analyzes behavior and favors a gray, centered layout.",
    "See https://example.org/colour/behaviour for the source.",  # spelling-ok
    "Read docs/organisation/centre.md first.",  # spelling-ok
    "Run ./colour/tool or ../behaviour/tool.",  # spelling-ok
    "It lives in /srv/colour/data on the host.",  # spelling-ok
    "Edit app/i18n/colour.json, then reload.",  # spelling-ok
]

# Prose with a slash is prose, not a path, and a URL is only the URL: each
# British word outside one is still caught.
SLASHED_PROSE = [
    ("Pick a colour/flavour for it.", ["colour", "flavour"]),  # spelling-ok
    ("Notes on labour/delivery.", ["labour"]),  # spelling-ok
    ("the centre/periphery split", ["centre"]),  # spelling-ok
    # A segment ending in a dot is not a file extension.
    ("And so on...colour/flavour now.", ["colour", "flavour"]),  # spelling-ok
    ("Then colour./flavour now.", ["colour", "flavour"]),  # spelling-ok
    # Nor is a dot inside a segment: the extension runs to the segment's end.
    ("Pick colour/flavour.x-ray now.", ["colour", "flavour"]),  # spelling-ok
    # A URL ends at whitespace, not at the end of the line.
    ("See https://example.org/x for the colour.", ["colour"]),  # spelling-ok
    # A URL has "://" or a scheme written without it: a colon alone is not one.
    ("A note:colour here.", ["colour"]),  # spelling-ok
]


def rows(table: str) -> list[tuple[str, str]]:
    out = []
    for line in table.strip().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        british, american = line.split()[:2]
        out.append((british, american))
    return out


TABLE_ROWS = rows(TABLE)


def words_of(rows_: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Each row as the single words it is made of (a hyphenated row, split)."""
    out = []
    for british, american in rows_:
        for b, a in zip(british.split("-"), american.split("-"), strict=True):
            if b != a:
                out.append((b, a))
    return out


HIT = re.compile(r":(\d+):(\d+): British spelling '([^']+)' -- use '([^']+)'")


def scan(
    mod: ModuleType,
    lines: list[str],
    allow: list[tuple[str, str]] | None = None,
    name: str = "sample.md",
) -> dict:
    """Run mod.check on a file of `lines`; return {line number: [(word, fix)]}.
    `name` may have directories, which are made under a temporary one."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        problems = mod.check(path, allow or [])
    found: dict[int, list[tuple[str, str]]] = {}
    for msg in problems:
        m = HIT.search(msg)
        if m:
            found.setdefault(int(m.group(1)), []).append((m.group(3), m.group(4)))
    return found


def suggested(
    mod: ModuleType,
    text: str,
    allow: list[tuple[str, str]] | None = None,
    name: str = "sample.md",
) -> str:
    """The text the --fix patch would make of a file of `text`. The file itself
    must be left as written, or the result says so."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(text.encode("utf-8"))
        after = mod.suggest(path, allow or [])[1]
        if path.read_bytes() != text.encode("utf-8"):
            return "suggest() wrote the file"
        return after


def cased(word: str, like: str) -> str:
    if like.isupper():
        return word.upper()
    if like[0].isupper():
        return word[0].upper() + word[1:]
    return word


# ---------------------------------------------------------------------------
# Properties. Each takes the module under test and returns the names of the
# properties that failed, so the mutation tests can run them on a broken copy.
# ---------------------------------------------------------------------------

CONTEXTS: list[tuple[str, Callable[[str], str], Callable[[str], str]]] = [
    ("prose", lambda w: f"The {w} matters here.", lambda w: w),
    ("a code comment", lambda w: f"x = 1  # the {w} of it", lambda w: w),
    ("a string", lambda w: f'label = "{w}"', lambda w: w),
    ("snake_case", lambda w: f"my_{w}_value = 2", lambda w: w),
    ("kebab-case", lambda w: f"data-{w}-id", lambda w: w),
    ("camelCase", lambda w: f"get{w.capitalize()}Value()", lambda w: w.capitalize()),
    ("Title case", lambda w: f"{w.capitalize()} first.", lambda w: w.capitalize()),
    ("UPPER CASE", lambda w: f"A {w.upper()} SHOUT", lambda w: w.upper()),
    ("UPPER_SNAKE", lambda w: f"MAX_{w.upper()}_SIZE = 3", lambda w: w.upper()),
]


def every_word(mod: ModuleType) -> list[str]:
    """Every British word the checker generates, and every word of the table (the
    segment words are not generated), in every context, with its fix."""
    bad = []
    words = sorted(set(mod.BRITISH.items()) | set(words_of(TABLE_ROWS)))
    for label, make, shape in CONTEXTS:
        lines = [make(w) for w, _ in words]
        found = scan(mod, lines)
        missed = [
            w
            for n, (w, a) in enumerate(words, 1)
            if found.get(n) != [(shape(w), cased(a, shape(w)))]
        ]
        if missed:
            bad.append(f"every listed word caught in {label} (missed {missed[:5]})")
    return bad


def table(mod: ModuleType) -> list[str]:
    """Every row of the hand-written table is caught, with the American form the
    table names. A word, stem, ending, prefix or segment dropped from the checker
    leaves its row uncaught."""
    lines = [f"The {b} here." for b, _ in TABLE_ROWS]
    found = scan(mod, lines)
    missed = []
    for n, (b, a) in enumerate(TABLE_ROWS, 1):
        want = [
            (wb, wa)
            for wb, wa in zip(b.split("-"), a.split("-"), strict=True)
            if wb != wa
        ]
        if found.get(n) != want:
            missed.append(f"{b}->{found.get(n)}")
    bad = [f"the table is caught (missed {missed[:8]})"] if missed else []
    # Every row is listed, so the patch suggests each one written alone. A row
    # found only by its shape would be reported and left out of the patch.
    single = [(b, a) for b, a in TABLE_ROWS if "-" not in b]
    text = "".join(f"The {b} here.\n" for b, _ in single)
    want = "".join(f"The {a} here.\n" for _, a in single)
    got = suggested(mod, text)
    if got != want:
        lines = zip(text.splitlines(), got.splitlines(), want.splitlines(), strict=True)
        wrong = [line for line, g, w in lines if g != w]
        bad.append(f"the patch suggests every row of the table ({wrong[:8]})")
    return bad


def ligatures(mod: ModuleType) -> list[str]:
    found = scan(mod, [f"The {b} here." for b, _ in LIGATURE_ROWS])
    want = {n: [row] for n, row in enumerate(LIGATURE_ROWS, 1)}
    bad = [] if found == want else [f"ligatures are caught ({found})"]
    text = "A manœuvre and an œdema.\n"  # spelling-ok
    got = suggested(mod, text)
    if got != "A maneuver and an edema.\n":
        bad.append(f"the patch respells a ligature ({got!r})")
    return bad


def american_left_alone(mod: ModuleType) -> list[str]:
    words = AMERICAN.split()
    found = scan(mod, [f"The {w} here." for w in words] + CLEAN)
    named = {n: (words + CLEAN)[n - 1] for n in found}
    return [f"no false positives (flagged {sorted(named.items())[:5]})"] * bool(found)


def capitalized(mod: ModuleType) -> list[str]:
    """A capitalized word is reported and left for a person; so is a word inside
    an identifier."""
    bad = []
    found = scan(mod, [line for line, _ in CAPITALIZED])
    got = {n: [w for w, _ in hits] for n, hits in found.items()}
    want = {n: words for n, (_, words) in enumerate(CAPITALIZED, 1) if words}
    if got != want:
        bad.append(f"a capitalized word is reported ({got})")
    text = "\n".join(line for line, _ in CAPITALIZED) + "\n"
    if suggested(mod, text) != text:
        bad.append(f"the patch leaves a capitalized word ({suggested(mod, text)!r})")
    found = scan(mod, [line for line, _ in IDENTIFIERS])
    got = {n: [a for _, a in hits] for n, hits in found.items()}
    want = {n: [a] for n, (_, a) in enumerate(IDENTIFIERS, 1)}
    if got != want:
        bad.append(f"an identifier's part is reported ({got})")
    text = "\n".join(line for line, _ in IDENTIFIERS) + "\n"
    if suggested(mod, text) != text:
        bad.append(f"the patch leaves an identifier ({suggested(mod, text)!r})")
    # The report says which hits the patch leaves, why, and only those.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.md"
        text = "Haemorrhage here.\nthe colour here.\n"  # spelling-ok
        path.write_text(text, encoding="utf-8")
        messages = mod.check(path, [])
    left = [mod.LEFT_FOR_A_HUMAN in m for m in messages]
    named = [mod.Left.CAPITALIZED in m for m in messages]
    if (
        left != [True, False]
        or named != [True, False]
        or "may be a name" not in mod.Left.CAPITALIZED
    ):
        bad.append(f"the report says what the patch leaves, and why ({messages})")
    return bad


def not_prose(mod: ModuleType) -> list[str]:
    """URLs of every scheme, email addresses, domains, file names, digests and
    encoded data are neither reported nor rewritten."""
    bad = []
    if list(mod.SCHEMES) != SCHEMES or list(mod.TLDS) != TLDS:
        bad.append("SCHEMES or TLDS is not the list the test pins")
    lines = [
        *NOT_PROSE,
        *(f"{scheme}:colour" for scheme in SCHEMES),  # spelling-ok
        *(f"see colour.{tld} now" for tld in TLDS),  # spelling-ok
        *(f"see colour.{tld}/path?behaviour=1" for tld in TLDS),  # spelling-ok
    ]
    found = scan(mod, lines)
    if found:
        bad.append(f"text that is not prose is left alone ({found})")
    text = "\n".join(lines) + "\n"
    if suggested(mod, text) != text:
        bad.append("the patch leaves text that is not prose")
    return bad


CORPUS = ROOT / "tests" / "fixtures" / "spelling_corpus"


def corpus_lines(name: str) -> list[str]:
    text = (CORPUS / name).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line and not line.startswith("# ")]


def corpus(mod: ModuleType) -> list[str]:
    """The verifier's corpus (#169): American words, organisms, places, titles,
    names, code and hex produce no finding; names with a capitalized British
    word are not in the patch; every British line is found, and suggested
    exactly; every medical word and every word after an opener is found."""
    bad = []
    clean = (
        corpus_lines("clean.txt")
        + corpus_lines("unlisted.txt")
        + corpus_lines("american.txt")
    )
    found = scan(mod, clean)
    if found:
        flagged = {clean[n - 1]: hits for n, hits in found.items()}
        bad.append(f"the corpus's clean lines produce no finding ({flagged})")

    wrap = (CORPUS / "wrap.md").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wrap.md"
        path.write_text(wrap, encoding="utf-8")
        if mod.check(path, []):
            bad.append("a binomial wrapped across lines is left alone")

    names = "\n".join(corpus_lines("names.txt")) + "\n"
    got = suggested(mod, names)
    if got != names:
        changed = [
            (a, b)
            for a, b in zip(names.splitlines(), got.splitlines(), strict=True)
            if a != b
        ]
        bad.append(f"the patch leaves the corpus's names alone ({changed[:5]})")

    rows = [line.split("  =>  ") for line in corpus_lines("british.txt")]
    found = scan(mod, [british for british, _ in rows])
    missed = [rows[n][0] for n in range(len(rows)) if n + 1 not in found]
    if missed:
        bad.append(f"the corpus's British lines are found (missed {missed})")
    text = "\n".join(british for british, _ in rows) + "\n"
    want = "\n".join(american for _, american in rows) + "\n"
    got = suggested(mod, text)
    if got != want:
        wrong = [
            (a, b)
            for a, b in zip(want.splitlines(), got.splitlines(), strict=False)
            if a != b
        ]
        bad.append(f"the patch suggests the corpus's British lines ({wrong[:5]})")

    words = corpus_lines("medical.txt")
    found = scan(mod, [f"The patient had {w} noted today." for w in words])
    missed = [
        w for n, w in enumerate(words, 1) if [h for h, _ in found.get(n, [])] != [w]
    ]
    if missed:
        bad.append(f"every medical word is reported (missed {missed[:10]})")
    openers = corpus_lines("openers.txt")
    found = scan(mod, openers)
    missed = [line for n, line in enumerate(openers, 1) if n not in found]
    if missed:
        bad.append(f"a word after any capitalized word is reported ({missed[:10]})")

    python = corpus_lines("python.txt")
    found = scan(mod, python, mod.load_allowlist(), name="corpus.py")
    if found:
        bad.append(f"Python's own spelling is left alone in a .py file ({found})")

    # The verifier's --fix demonstration: a CSS and a Markdown file, which the
    # first version of this checker corrupted. Now nothing is suggested: each
    # hit is a capitalized name.
    demo = (CORPUS / "fixdemo.txt").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / "a.css", Path(tmp) / "a.md"]
        for path in paths:
            path.write_text(demo, encoding="utf-8")
        with (
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            code = mod.main(["--fix", *map(str, paths)])
        after = [path.read_text(encoding="utf-8") for path in paths]
        reported = [
            (m.group(3), m.group(4))
            for path in paths
            for m in map(HIT.search, mod.check(path, []))
            if m
        ]
    if after != [demo, demo]:
        bad.append(f"--fix leaves the demonstration as written ({after})")
    if out.getvalue():
        bad.append(f"the demonstration's names are not in the patch ({out.getvalue()})")
    if code != 1 or err.getvalue().count(mod.LEFT_FOR_A_HUMAN) != 4:
        bad.append(f"--fix lists each hit by hand, exits 1 ({code}, {err.getvalue()})")
    names = ("Haematology", "Sulphur")  # spelling-ok
    want_reported = [(names[0], "Hematology"), (names[1], "Sulfur")] * 2
    if reported != want_reported:
        bad.append(f"the demonstration's names are reported ({reported})")
    return bad


def python_protocol(mod: ModuleType) -> list[str]:
    """With the real .spelling-allow, `.cancelled()` is exempt only as a method
    call in a .py file: the word in a comment, a docstring or a bare call is
    still caught, and the method call is caught outside Python."""
    word = "cancelled"  # spelling-ok
    allow = mod.load_allowlist()
    lines = [
        f"if task.{word}():",
        f"    return fut.{word}()",
        f"# the job was {word}",
        f"{word}()",
        f'"""Whether it was {word}."""',
    ]
    found = scan(mod, lines, allow, name="tool.py")
    bad = []
    if sorted(found) != [3, 4, 5]:
        bad.append(f".{word}() is exempt only as a method call in Python ({found})")
    found = scan(mod, [f"if task.{word}():"], allow, name="notes.md")
    if not found:
        bad.append(f".{word}() is not exempt outside Python")
    return bad


# Exactly the directories a whole-repository run skips, so one added to hide
# files, or one dropped, is noticed.
SKIPPED_DIRS = {
    ".git",
    ".pixi",
    "site",
    ".cache",
    "node_modules",
    ".venv",
    "venv",
    "backups",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}


def skip_dirs(mod: ModuleType) -> list[str]:
    if mod.SKIP_DIRS == SKIPPED_DIRS:
        return []
    return [f"SKIP_DIRS is exactly its entries ({mod.SKIP_DIRS ^ SKIPPED_DIRS})"]


def fix_exit_codes(mod: ModuleType) -> list[str]:
    """main() with --fix: 0 when there is no hit, 1 when there is a suggestion,
    a hit to fix by hand, or a file it could not read."""
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean.md"
        clean.write_text("the color\n", encoding="utf-8")
        good = Path(tmp) / "good.md"
        good.write_text("the colour\n", encoding="utf-8")  # spelling-ok
        latin = Path(tmp) / "latin1.md"
        latin.write_bytes("Our café.\n".encode("latin-1"))
        name = Path(tmp) / "name.md"
        name.write_text("Colour Springs\n", encoding="utf-8")  # spelling-ok
        # Inside the repository, so the suggestion is one the patch can name.
        codes = [
            run_fix(mod, Path(tmp), [str(path)])[0]
            for path in (clean, good, latin, name)
        ]
    return [] if codes == [0, 1, 1, 1] else [f"--fix exits 0, 1, 1, 1 ({codes})"]


def unopenable_is_text(mod: ModuleType) -> list[str]:
    """A file is_text() cannot open counts as text, so check() reports it."""
    with tempfile.TemporaryDirectory() as tmp:
        ok = mod.is_text(Path(tmp)) and mod.is_text(Path(tmp) / "gone.md")
    return [] if ok else ["a file that cannot be opened counts as text"]


def corpus_skipped(mod: ModuleType) -> list[str]:
    """The files of the spelling corpus are skipped, and nothing else is."""
    rel = "tests/fixtures/spelling_corpus"
    want = [
        (f"{rel}/clean.txt", True),
        (f"{rel}/british.txt", True),
        (f"{rel}/wrap.md", True),
        (f"{rel}/sub/notes.md", False),
        (f"{rel}.md", False),
        ("tests/fixtures/snapshot_default.json", False),
        ("tests/fixtures/notes.md", False),
    ]
    wrong = [r for r, skipped in want if mod.skip(ROOT / r) != skipped]
    return [f"only the corpus's own files are skipped ({wrong})"] if wrong else []


def slashes_in_prose(mod: ModuleType) -> list[str]:
    found = scan(mod, [line for line, _ in SLASHED_PROSE])
    got = {n: [w for w, _ in hits] for n, hits in found.items()}
    want = {n: words for n, (_, words) in enumerate(SLASHED_PROSE, 1)}
    return [] if got == want else [f"a slash in prose is not a path ({got})"]


def case_folding(mod: ModuleType) -> list[str]:
    word = "behaviour"  # spelling-ok
    found = scan(mod, [word, word.capitalize(), word.upper()])
    return [] if len(found) == 3 else [f"case variants caught ({found})"]


def spelling_ok(mod: ModuleType) -> list[str]:
    """The marker exempts its own line, and only as written: lowercase."""
    lines = [
        "The colour is quoted.  <!-- spelling-ok -->",  # spelling-ok
        "The colour is not.",  # spelling-ok
        "spelling ok is not the marker: colour",  # spelling-ok
        "The colour.  # SPELLING-OK is not the marker either",  # spelling-ok
    ]
    found = scan(mod, lines)
    ok = sorted(found) == [2, 3, 4]
    return [] if ok else [f"spelling-ok is per line, in lowercase ({found})"]


GHA = "cancelled"  # spelling-ok
PHRASE = f"the '{GHA}' state"


def allowlist(mod: ModuleType) -> list[str]:
    """An allowed phrase exempts itself, exactly as written, in the files its glob
    names, and nothing else."""
    bad = []
    allow = [("*.md", PHRASE)]
    lines = [
        f"if result == {PHRASE}:",
        f"if result == {PHRASE}: the behaviour too",  # spelling-ok
        "if result == 'cancelled':",  # spelling-ok
        "if result == the 'Cancelled' state:",  # spelling-ok
        "if result == THE 'CANCELLED' STATE:",  # spelling-ok
        # The phrase is exempt as a whole, not word by word: its quoted word
        # elsewhere on the same line is still caught.
        f"Keep {PHRASE}; '{GHA}' alone is wrong.",
    ]
    found = scan(mod, lines, allow)
    british = ("behaviour", "cancelled", "Cancelled", "CANCELLED")  # spelling-ok
    want = {
        2: [(british[0], "behavior")],
        3: [(british[1], "canceled")],
        4: [(british[2], "Canceled")],
        5: [(british[3], "CANCELED")],
        6: [(british[1], "canceled")],
    }
    if found != want:
        bad.append(f"an allowed phrase exempts only itself, in its own case ({found})")

    # A phrase in mixed case is matched as written: not folded either way.
    error = "CancelledError"  # spelling-ok
    lines = [
        f"except asyncio.{error}:",
        f"x = {error[0].lower()}{error[1:]}",
        f"X = {error[:9]}{error[9:].upper()}",
    ]
    found = scan(mod, lines, [("*.py", error)], name="tool.py")
    if sorted(found) != [2, 3]:
        bad.append(f"a mixed-case phrase is matched as written ({found})")

    # Scoped: allowed in a workflow, not in Markdown, Python, or a .yml file
    # anywhere else.
    workflows = ".github/workflows/*.yml"
    for name, scope, exempt in [
        ("ci.yml", "*.yml", True),
        ("notes.md", "*.yml", False),
        ("tool.py", workflows, False),
        ("tool.py", "*.py", True),
        (".github/workflows/ci.yml", workflows, True),
        ("other/ci.yml", workflows, False),
        ("ci.yml", workflows, False),
        (".github/ci.yml", workflows, False),
    ]:
        hits = scan(mod, [f"x = {PHRASE}"], [(scope, PHRASE)], name=name)
        if bool(hits) == exempt:
            verb = "exempts" if exempt else "does not exempt"
            bad.append(f"the glob {scope!r} {verb} {name}")

    # A real workflow file, read from the repository root: the glob is matched
    # against the path from ROOT, not the file's name.
    for rel, exempt in [
        (".github/workflows/test.yml", True),
        ("compose.yaml", False),
        ("docs/ci.yml", False),
    ]:
        got = mod.allowed_in(ROOT / rel, [(workflows, PHRASE)])
        if got != ([PHRASE] if exempt else []):
            bad.append(f"the glob {workflows!r} on {rel} gives {got}")

    # A line with no glob is refused, not read as allowed everywhere.
    for text in [f"{GHA}()", f"'{GHA}'", f": {GHA}()", "*.yml:"]:
        try:
            mod.parse_allowlist(text)
        except ValueError:
            continue
        bad.append(f"an unscoped allowlist line is refused ({text!r})")
    try:
        parsed = mod.parse_allowlist(
            f"# a comment\n\n.github/workflows/*.yml: {GHA}()\n*.py: X\n"
        )
    except ValueError as error:
        parsed = repr(error)
    want_parsed = [
        (".github/workflows/*.yml", f"{GHA}()"),
        ("*.py", "X"),
    ]  # spelling-ok
    if parsed != want_parsed:
        bad.append(f"a scoped allowlist line is read ({parsed})")
    return bad


def unreadable(mod: ModuleType) -> list[str]:
    """A file that is not UTF-8, or cannot be read at all, is reported, not
    passed in silence."""
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "latin1.md"
        path.write_bytes("The colour of café.\n".encode("latin-1"))  # spelling-ok
        problems = mod.check(path, [])
        ok = len(problems) == 1 and "UTF-8" in problems[0]
        if not ok:
            bad.append(f"a file that is not UTF-8 is reported ({problems})")
        for what, path in [
            ("a directory", Path(tmp)),
            ("a missing file", Path(tmp) / "gone.md"),
        ]:
            problems = mod.check(path, [])
            ok = len(problems) == 1 and "could not be read" in problems[0]
            if not ok:
                bad.append(f"{what} is reported, not passed ({problems})")
    return bad


def fixes(mod: ModuleType) -> list[str]:
    # A capitalized word may be a name and an identifier may be someone else's:
    # the patch leaves each. A lowercase word after a capitalized one that is no
    # genus is suggested.
    text = (
        "Behaviour, BEHAVIOUR and behaviour;\n"  # spelling-ok
        "a colourPicker and MAX_COLOURS.\n"  # spelling-ok
        "The colour stays.  <!-- spelling-ok -->\n"  # spelling-ok
        "See https://example.org/colour for it.\n"  # spelling-ok
        f"Keep {PHRASE} but fix the centre.\n"  # spelling-ok
        "Our judgements, unrecognised.\n"  # spelling-ok
        "Haemorrhagic oedematous foetuses.\n"  # spelling-ok
        "the colour, the grey and the centre.\n"  # spelling-ok
    )
    want = (
        "Behaviour, BEHAVIOUR and behavior;\n"  # spelling-ok
        "a colourPicker and MAX_COLOURS.\n"  # spelling-ok
        "The colour stays.  <!-- spelling-ok -->\n"  # spelling-ok
        "See https://example.org/colour for it.\n"  # spelling-ok
        f"Keep {PHRASE} but fix the center.\n"
        "Our judgments, unrecognized.\n"
        "Haemorrhagic edematous fetuses.\n"  # spelling-ok
        "the color, the gray and the center.\n"
    )
    got = suggested(mod, text, [("*.md", PHRASE)])
    return [] if got == want else [f"the patch keeps case and exemptions ({got!r})"]


# Files of every kind the checker must read, each with a British word in it:
# every kind pre-commit's `types: [text]` passes, so a whole-repository run and
# the hook read the same files.
SCANNED = [
    "app/style.css",
    "docs/page.html",
    "requirements.txt",
    "docs/notes.rst",
    "Makefile",
    "scripts/run.sh",
    "proxy/site.caddy",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    ".trivyignore",
    "LICENSE",
    "app/icon.svg",
    "pixi.lock",
    "pkg/module.py",
    "app/js/50-view/10-panel.js",
    "data/table.json",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "compose.yaml",
    "Caddyfile",
    "proxy/Caddyfile",
    "proxy/Dockerfile",
    "app/i18n/en.json",
    "app/i18n/framework/en.json",
    "docs/developing.md",
    "scripts/tool.py",
    "server/schema.sql",
    # Terminal output: an escape byte is text, by identify's rule.
    "logs/ansi.log",
    # So are BEL, BS, VT and FF.
    "logs/bell.log",
]
# Translations, which the checker must not judge by English spelling (#80); a
# binary file, which pre-commit would not call text; and a symbolic link, which
# pre-commit does not pass (its target is read on its own).
NOT_SCANNED = [
    "app/i18n/de.json",
    "app/i18n/framework/fr.json",
    "app/logo.png",
    "docs/link.md",
    # A DEL byte makes a file binary, by the same rule.
    "data/del.dat",
]


def scanned(mod: ModuleType) -> list[str]:
    """targets() and skip() together: which files a whole-repository run reads."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel in SCANNED + NOT_SCANNED:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            word = "colour"  # spelling-ok
            json_file = rel.endswith(".json")
            body = f'{{"note": "the {word}"}}\n' if json_file else f"# the {word}\n"
            if rel.endswith(".png"):
                path.write_bytes(b"\x89PNG\r\n\x1a\n\x00" + body.encode())
            elif rel == "logs/ansi.log":
                path.write_bytes(b"\x1b[31m" + body.encode())
            elif rel == "logs/bell.log":
                path.write_bytes(b"\x07\x08\x0b\x0c" + body.encode())
            elif rel == "data/del.dat":
                path.write_bytes(b"\x7f" + body.encode())
            elif rel == "docs/link.md":
                path.symlink_to(root / "docs/page.html")
            else:
                path.write_text(body, encoding="utf-8")
        saved = mod.ROOT
        mod.ROOT = root
        try:
            reported = {
                str(p.relative_to(root))
                for p in mod.targets([])
                if not mod.skip(p) and mod.check(p, [])
            }
        finally:
            mod.ROOT = saved
    bad = []
    missed = [rel for rel in SCANNED if rel not in reported]
    if missed:
        bad.append(f"every kind of file is read (missed {missed})")
    judged = [rel for rel in NOT_SCANNED if rel in reported]
    if judged:
        bad.append(f"a translation is not judged by English spelling ({judged})")
    return bad


# Real files of ours, which must never be skipped.
REAL = [
    "app/js/00-core/00-util.js",
    "app/i18n/en.json",
    "docs/developing.md",
    "scripts/check_enums.py",
    "proxy/Caddyfile",
    "compose.yaml",
    ".github/workflows/test.yml",
    "tests/test_check_spelling.py",
]


def real_files_read(mod: ModuleType) -> list[str]:
    skipped = [rel for rel in REAL if mod.skip(ROOT / rel)]
    return [f"our own files are not skipped ({skipped})"] if skipped else []


# Exactly what is quoted verbatim, so an entry added to hide a file is noticed.
QUOTED = {
    "data/chai_te_metrics.json",
    "docs/frameworks/chai-metrics.md",
    "app/js/10-frameworks/10-chai/05-te-metrics.js",
    "docs/app/index.html",
}


def quoted_verbatim(mod: ModuleType) -> list[str]:
    if mod.QUOTED_VERBATIM == QUOTED:
        return []
    return [f"QUOTED_VERBATIM is exactly its entries ({mod.QUOTED_VERBATIM ^ QUOTED})"]


TRANSLATIONS = [
    ("app/i18n/de.json", True),
    ("app/i18n/framework/fr.json", True),
    ("app/i18n/en.json", False),
    ("app/i18n/framework/en.json", False),
    ("app/i18n/de.json/notes.md", False),
    ("app/i18n/framework/de.json/notes.md", False),
    ("app/i18n/sub/de.json", False),
    ("docs/app/i18n/de.json", False),
    ("app/i18n/de.yaml", False),
]


def translations(mod: ModuleType) -> list[str]:
    wrong = [rel for rel, want in TRANSLATIONS if mod.is_translation(rel) != want]
    return [f"is_translation() reads only a catalog ({wrong})"] if wrong else []


# ---------------------------------------------------------------------------
# What the --fix patch suggests, what it leaves for a person, and that nothing
# is ever written (D-81).
# ---------------------------------------------------------------------------

W = "colour"  # spelling-ok
# Each row is (line, the line the suggestion patch makes of it in a Markdown
# file, the name of the Left member it is reported with, or None when the patch
# suggests it).
FIX_CASES: list[tuple[str, str, str | None]] = [
    (f"the {W} here", "the color here", None),
    (W, "color", None),
    # What may stand next to a word the patch suggests.
    *[(f"the {c}{W} here", f"the {c}color here", None) for c in "([\"'*"],
    *[(f"the {W}{c} here", f"the color{c} here", None) for c in ")]\"'*,;:.!?"],
    (f"the **{W}**.", "the **color**.", None),
    (f"the ({W}).", "the (color).", None),
    (f"| a | {W} |", "| a | color |", None),
    (f"- {W}", "- color", None),
    (f"> {W}", "> color", None),
    # And what may not: anything else, before or after.
    *[(f"the {c}{W} here", "", "JOINED") for c in "_-@:.=<>`~#$%&+\\^{|}0"],
    *[(f"the {W}{c} here", "", "JOINED") for c in "_-/@=<>`~#$%&+\\^{|}(0"],
    (f"the {W}'s here", "", "JOINED"),
    (f"the {W}.x here", "", "JOINED"),
    (f"the {W}:x here", "", "JOINED"),
    (f"the “{W}” here", "", "JOINED"),
    (f"the _{W}_ here", "", "JOINED"),
    # The verifier's cases (#169).
    ("_Oestrus ovis_", "", "CAPITALIZED"),  # spelling-ok
    ("_British Journal of Anaesthesia_", "", "CAPITALIZED"),  # spelling-ok
    ("__Haemophilia__", "", "CAPITALIZED"),  # spelling-ok
    ("@Grey2019", "", "CAPITALIZED"),  # spelling-ok
    ("@article{Grey2019,", "", "CAPITALIZED"),  # spelling-ok
    ("Oestrus_ovis", "", "CAPITALIZED"),  # spelling-ok
    ("GBIF:Oestrus_ovis", "", "CAPITALIZED"),  # spelling-ok
    ("Centre_County", "", "CAPITALIZED"),  # spelling-ok
    ("OpenGrey", "", "CAPITALIZED"),  # spelling-ok
    ("Sulphur8", "", "CAPITALIZED"),  # spelling-ok
    ("MonoBehaviour", "", "CAPITALIZED"),  # spelling-ok
    ("cmap='Greys_r'", "", "CAPITALIZED"),  # spelling-ok
    ("01H8XGJWBWBAQ4Z1HXKT2GREY7", "", "CAPITALIZED"),  # spelling-ok
    ("import colour", "", "CODE"),  # spelling-ok
    ("library (colour)", "", "CODE"),  # spelling-ok
    ("See import colour, page 3.", "", "CODE"),  # spelling-ok
    ("aes(colour=)", "", "JOINED"),  # spelling-ok
    ("ggplot(df, aes(colour = arm))", "", "JOINED"),  # spelling-ok
    ("scale_colour_manual(values = pal)", "", "JOINED"),  # spelling-ok
    ("grey.colors()", "", "JOINED"),  # spelling-ok
    ("@behaviour GenServer", "", "JOINED"),  # spelling-ok
    ("pip install colour-science", "", "JOINED"),  # spelling-ok
    ("if task.cancelled():", "", "JOINED"),  # spelling-ok
    # Whatever capitalized word stands before it, a listed lowercase word is
    # suggested: only a binomial's epithet is skipped (BINOMIALS).
    ("in Boston grey skies", "in Boston gray skies", None),  # spelling-ok
    ("Severe oedema", "Severe edema", None),  # spelling-ok
    ("The foetus grew.", "The fetus grew.", None),  # spelling-ok
    ("In Boston, grey skies", "In Boston, gray skies", None),  # spelling-ok
    ("HbA1c grey", "HbA1c gray", None),  # spelling-ok
    # Code in prose.
    ("from colour import x", "", "CODE"),  # spelling-ok
    ("- import colour", "", "CODE"),  # spelling-ok
    ("$ grey --help", "", "CODE"),  # spelling-ok
    (">>> grey", "", "CODE"),  # spelling-ok
    ("run `set grey now` then", "", "CODE"),  # spelling-ok
    ("run ``set grey now`` then", "", "CODE"),  # spelling-ok
    ("    the grey", "", "CODE"),  # spelling-ok
    ("\tthe grey", "", "CODE"),  # spelling-ok
    # Found by its shape: reported with a suggestion, never rewritten.
    ("the haematoxylin stain", "", "SHAPE"),  # spelling-ok
]
# Neither reported nor rewritten: not English, or not prose.
NOT_READ = [
    "décentre réanalyse Décentre",  # spelling-ok
    "_ws://localhost/colour_",  # spelling-ok
]


def fix_cases(mod: ModuleType) -> list[str]:
    """Each row of FIX_CASES, in a Markdown file: what the patch makes of it,
    and why the report says it was left."""
    bad = []
    for line, want, reason in FIX_CASES:
        want = want or line
        got = suggested(mod, line + "\n")
        if got != want + "\n":
            bad.append(f"the patch makes {want!r} of {line!r} ({got!r})")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            path.write_text(line + "\n", encoding="utf-8")
            messages = mod.check(path, [])
        note = "" if reason is None else mod.left_note(mod.Left[reason])
        ok = len(messages) == 1 and (
            note in messages[0] if reason else mod.LEFT_FOR_A_HUMAN not in messages[0]
        )
        if not ok:
            bad.append(
                f"{line!r} is reported once, {reason or 'suggested'} ({messages})"
            )
    for line in NOT_READ:
        if scan(mod, [line]) or suggested(mod, line + "\n") != line + "\n":
            bad.append(f"{line!r} is neither reported nor suggested")
    return bad


# The epithet of a binomial is skipped, listed or by its shape, after a genus
# in GENERA or an abbreviated one; after any other word, or with an English
# ending, it is reported. Each row is (line, the words reported).
BINOMIALS = [
    ("Tritrichomonas foetus", []),  # spelling-ok
    ("*Tritrichomonas foetus* in cattle", []),  # spelling-ok
    ("*Tritrichomonas* *foetus* in cattle", []),  # spelling-ok
    ("<i>Tritrichomonas</i> <i>foetus</i>", []),  # spelling-ok
    ("Tritrichomonas&nbsp;foetus", []),  # spelling-ok
    ("T. foetus in cattle", []),  # spelling-ok
    ("Campylobacter foetus subsp. venerealis", []),  # spelling-ok
    ("_Schistosoma haemobium_ eggs", []),  # spelling-ok
    ("Enterococcus (E.) haemobium", []),  # spelling-ok
    ("Severe foetus", ["foetus"]),  # spelling-ok
    ("Tritrichomonas, foetus", ["foetus"]),  # spelling-ok
    ("Enterococcus faecal contamination", ["faecal"]),  # spelling-ok
    ("Enterococcus praecordial pain", ["praecordial"]),  # spelling-ok
    ("Streptococcus haematogenous spread", ["haematogenous"]),  # spelling-ok
    ("the foetus", ["foetus"]),  # spelling-ok
    # Still skipped: a true Latin epithet, listed or by its shape.
    ("Enterococcus faecalis", []),  # spelling-ok
    ("Staphylococcus haemolyticus", []),  # spelling-ok
    ("Mycoplasma haemocanis", []),  # spelling-ok
    ("B. foetus in bulls", []),  # spelling-ok
    # An English medical word after a genus is reported (the verifier's seventh
    # pass): listed ones, each English ending, and across a line.
    ("Staphylococcus bacteraemia", ["bacteraemia"]),  # spelling-ok
    ("Campylobacter diarrhoea", ["diarrhoea"]),  # spelling-ok
    ("Streptococcus septicaemia", ["septicaemia"]),  # spelling-ok
    ("Clostridium diarrhoea", ["diarrhoea"]),  # spelling-ok
    ("Enterococcus bacteraemia", ["bacteraemia"]),  # spelling-ok
    ("Haemophilus bacteraemia", ["bacteraemia"]),  # spelling-ok
    ("Neisseria gonorrhoea", ["gonorrhoea"]),  # spelling-ok
    ("Mycoplasma oesophagitis", ["oesophagitis"]),  # spelling-ok
    ("See Appendix B. oedema", ["oedema"]),  # spelling-ok
    ("Hepatitis C. ischaemia", ["ischaemia"]),  # spelling-ok
    ("B. oesophagus", ["oesophagus"]),  # spelling-ok
    ("Infection with Clostridium", []),
    ("diarrhoea", ["diarrhoea"]),  # spelling-ok
    # Found by shape, not listed, so only the English ending tells.
    ("Streptococcus candidaemia", ["candidaemia"]),  # spelling-ok
    ("Haemophilus otorrhoea", ["otorrhoea"]),  # spelling-ok
    ("Streptococcus haemangioendothelioma", ["haemangioendothelioma"]),  # spelling-ok
    ("Clostridium caecitis", ["caecitis"]),  # spelling-ok
    ("Clostridium haemosiderosis", ["haemosiderosis"]),  # spelling-ok
    # An abbreviated genus is one capital and a period, after whitespace or the
    # start, and not after a word that is no genus (NOT_GENUS_WORDS).
    ("E. faecalis", []),  # spelling-ok
    ("T. foetus", []),  # spelling-ok
    ("S. haematobium eggs", []),  # spelling-ok
    ("M. haemolytica", []),  # spelling-ok
    ("*E.* foetus", []),  # spelling-ok
    ("(S.) haematobium", []),  # spelling-ok
    ("In cattle T. foetus", []),  # spelling-ok
    ("Twin A. foetus", ["foetus"]),  # spelling-ok
    ("Dr K. foetus", ["foetus"]),  # spelling-ok
    ("Dr. K. foetus", ["foetus"]),  # spelling-ok
    ("Prof. K. haemobium", ["haemobium"]),  # spelling-ok
    ("Hep B. foetus", ["foetus"]),  # spelling-ok
    ("Hep B. haemoperitoneum", ["haemoperitoneum"]),  # spelling-ok
    ("Group A. foetus", ["foetus"]),  # spelling-ok
    ("vitamin D. foetus", ["foetus"]),  # spelling-ok
    ("Fig. 2A. foetus", ["foetus"]),  # spelling-ok
    ("UK. foetus", ["foetus"]),  # spelling-ok
    ("Appendix B. oedema", ["oedema"]),  # spelling-ok
    ("xClostridium foetus", ["foetus"]),  # spelling-ok
    ("Dr K. caecum", ["caecum"]),  # spelling-ok
    ("Fig. B. haemobium", ["haemobium"]),  # spelling-ok
    ("Hepatitis B. haemobium", ["haemobium"]),  # spelling-ok
    # Written with a ligature, a listed word is still a listed word.
    ("E. œdema", ["œdema"]),  # spelling-ok
    # English -um and -a nouns after a genus are reported (NOT_EPITHETS); true
    # epithets that end so are skipped.
    ("Clostridium caecum perforation", ["caecum"]),  # spelling-ok
    ("Streptococcus haemoperitoneum", ["haemoperitoneum"]),  # spelling-ok
    ("Streptococcus haemopericardium", ["haemopericardium"]),  # spelling-ok
    ("Clostridium haematometra", ["haematometra"]),  # spelling-ok
    ("Clostridium praecordium", ["praecordium"]),  # spelling-ok
    ("Enterococcus faecium", []),  # spelling-ok
    ("Schistosoma haematobium", []),  # spelling-ok
    ("Mycobacterium haemophilum", []),  # spelling-ok
    # True epithets with an -ans, -ens or -os ending, listed in LATIN_EPITHETS,
    # are skipped after any genus and alone.
    ("Gemella haemolysans", []),  # spelling-ok
    ("Neisseria haemolysans", []),  # spelling-ok
    ("Clostridium oedematiens", []),  # spelling-ok
    ("Eimeria caecicola", []),  # spelling-ok
    ("Bos haemobos", []),  # spelling-ok
    # The butterfly is a "sulphur", reported as the British spelling of  # spelling-ok
    # sulfur in a name or not (documented in the checker's docstring).
    ("the clouded sulphur butterfly", ["sulphur"]),  # spelling-ok
]
# The words that make an initial no genus, and the English nouns that are never
# epithets, written out here so that dropping one from the checker is noticed.
NOT_GENUS = [
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
]
NEVER_EPITHETS = [
    "caecum",  # spelling-ok
    "haemoperitoneum",  # spelling-ok
    "haemopericardium",  # spelling-ok
    "haematometra",  # spelling-ok
    "praecordium",  # spelling-ok
]


def binomials(mod: ModuleType) -> list[str]:
    found = scan(mod, [line for line, _ in BINOMIALS])
    got = {n: [w for w, _ in hits] for n, hits in found.items()}
    want = {n: words for n, (_, words) in enumerate(BINOMIALS, 1) if words}
    bad = [] if got == want else [f"a binomial's epithet is skipped ({got})"]
    if set(mod.NOT_GENUS_WORDS) != set(NOT_GENUS) or set(mod.NOT_EPITHETS) != set(
        NEVER_EPITHETS
    ):
        bad.append("NOT_GENUS_WORDS or NOT_EPITHETS is not the list the test pins")
    lines = [f"{w.title()} A. foetus" for w in NOT_GENUS]  # spelling-ok
    lines += [f"Clostridium {w}" for w in NEVER_EPITHETS]  # spelling-ok
    reported = scan(mod, lines)
    if len(reported) != len(lines):
        bad.append(f"a listed non-genus word or non-epithet is skipped ({reported})")
    return bad


def fix_lines(mod: ModuleType) -> list[str]:
    """Across lines: a binomial broken at the end of a line, fenced, indented and
    literal blocks, the first column, and a last line with no newline."""
    bad = []
    g, a = "the grey", "the gray"  # spelling-ok
    cases = [
        ("a.md", "Tritrichomonas\nfoetus here\n", None),  # spelling-ok
        ("a.md", "<i>Tritrichomonas</i>\n<i>foetus</i> here\n", None),  # spelling-ok
        (
            "a.md",
            "Tritrichomonas\n\nfoetus here\n",  # spelling-ok
            "Tritrichomonas\n\nfetus here\n",
        ),
        ("a.md", f"```\n{g}\n```\n{g}\n", f"```\n{g}\n```\n{a}\n"),
        ("a.md", f"~~~\n{g}\n~~~\n{g}\n", f"~~~\n{g}\n~~~\n{a}\n"),
        ("a.md", f"````\n```\n{g}\n````\n{g}\n", f"````\n```\n{g}\n````\n{a}\n"),
        # A fence may be indented up to three spaces.
        ("a.md", f"  ```\n{g}\n  ```\n{g}\n", f"  ```\n{g}\n  ```\n{a}\n"),
        ("a.md", f"   ~~~\n{g}\n   ~~~\n{g}\n", f"   ~~~\n{g}\n   ~~~\n{a}\n"),
        ("a.rst", f"Example::\n\n    {g}\n\n{g}\n", f"Example::\n\n    {g}\n\n{a}\n"),
        (
            "a.rst",
            f".. code-block:: python\n\n    {g}\n\n{g}\n",
            f".. code-block:: python\n\n    {g}\n\n{a}\n",
        ),
        ("a.txt", f"    {g}\n", f"    {a}\n"),
        ("a.md", f"{g} x", f"{a} x"),
        ("a.md", W, "color"),
        ("a.md", f"x\n{W}", "x\ncolor"),
    ]
    for name, text, want in cases:
        want = text if want is None else want
        got = suggested(mod, text, name=name)
        if got != want:
            bad.append(f"the patch makes {want!r} of {text!r} in {name} ({got!r})")
    return bad


# Files of every kind: the patch suggests only in Markdown, reStructuredText
# and plain text (and the English catalog's values, below).
FILE_KINDS = [
    ("a.md", True),
    ("a.MD", True),
    ("a.txt", True),
    ("a.rst", True),
    ("a.py", False),
    ("a.js", False),
    ("a.json", False),
    ("a.yml", False),
    ("a.html", False),
    ("a.css", False),
    ("a.R", False),
    ("a.bib", False),
    ("a.tex", False),
    ("Makefile", False),
]


def file_kinds(mod: ModuleType) -> list[str]:
    bad = []
    line = f"the {W} here\n"
    for name, suggests in FILE_KINDS:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text(line, encoding="utf-8")
            reported = mod.check(path, [])
        got = suggested(mod, line, name=name)
        if (got != line) != suggests or len(reported) != 1:
            bad.append(f"{name} is {'' if suggests else 'not '}suggested ({got!r})")
        if not suggests and mod.Left.NOT_PROSE not in reported[0]:
            bad.append(f"{name}: the report says it is not prose ({reported})")
    return bad


CATALOG_TEXT = (
    "{\n"
    '  "@meta": {"safety": ["colour"]},\n'  # spelling-ok
    '  "colour": "the colour",\n'  # spelling-ok
    '  "pick": "Pick a colour or a {colour}"\n'  # spelling-ok
    "}\n"
)
CATALOG_WANT = (
    "{\n"
    '  "@meta": {"safety": ["colour"]},\n'  # spelling-ok
    '  "colour": "the color",\n'  # spelling-ok
    '  "pick": "Pick a color or a {colour}"\n'  # spelling-ok
    "}\n"
)


def catalog(mod: ModuleType) -> list[str]:
    """In app/i18n/en.json, only a value is suggested: not a key, an array's
    item, or the same file anywhere else."""
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        saved = mod.ROOT
        mod.ROOT = root
        try:
            for rel, expect in [
                ("app/i18n/en.json", CATALOG_WANT),
                ("app/i18n/framework/en.json", CATALOG_TEXT),
                ("docs/en.json", CATALOG_TEXT),
            ]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(CATALOG_TEXT, encoding="utf-8")
                got = mod.suggest(path, [])[1]
                if got != expect:
                    bad.append(f"the patch for {rel} ({got!r})")
        finally:
            mod.ROOT = saved
    return bad


def run_fix(mod: ModuleType, root: Path, argv: list[str]) -> tuple[int, str, str]:
    """main(["--fix", *argv]) with the repository root at `root`: its exit code,
    stdout (the patch) and stderr (the hits to fix by hand)."""
    saved = mod.ROOT, mod.ALLOWLIST
    mod.ROOT, mod.ALLOWLIST = root, root / ".spelling-allow"
    try:
        with (
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            code = mod.main(["--fix", *argv])
    finally:
        mod.ROOT, mod.ALLOWLIST = saved
    return code, out.getvalue(), err.getvalue()


def fix_respects_skip(mod: ModuleType) -> list[str]:
    """The patch never names a file skip() skips: something quoted verbatim, the
    corpus. Named on the command line, or found by a whole-repository run."""
    bad = []
    text = f"the {W} here\n"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rels = [
            sorted(r for r in mod.QUOTED_VERBATIM if r.endswith(".md"))[0],
            f"{mod.CORPUS}/notes.txt",
        ]
        for rel in rels:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        for argv in ([str(root / r) for r in rels], []):
            _, out, err = run_fix(mod, root, argv)
            named = [r for r in rels if r in out or r in err]
            if named:
                bad.append(f"the patch leaves skipped files ({argv[:1]}: {named})")
    return bad


# A modification time far in the past, so a write is seen even when the clock
# is coarse.
OLD_MTIME_NS = 1_000_000_000 * 10**9


def never_writes(mod: ModuleType) -> list[str]:
    """--fix writes nothing: no file's bytes or modification time change, for
    every kind of file, the English catalog, CRLF endings, a last line with no
    newline, and every file of the verifier's corpus (as written, and as
    Markdown), whether the files are named or found by a whole-repository run."""
    bad = []
    files = {name: f"the {W} here\n".encode() for name, _ in FILE_KINDS}
    files["app/i18n/en.json"] = CATALOG_TEXT.encode()
    files["crlf.md"] = b"the colour\r\nthe grey\r\n"  # spelling-ok
    files["no-newline.md"] = b"x\ncolour"  # spelling-ok
    for path in sorted(CORPUS.iterdir()):
        files[f"corpus/{path.name}"] = path.read_bytes()
        files[f"corpus/{path.stem}.md"] = path.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
            os.utime(root / rel, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        for argv in ([str(root / rel) for rel in files], []):
            code, _, _ = run_fix(mod, root, argv)
            changed = [
                rel
                for rel, data in files.items()
                if (root / rel).read_bytes() != data
                or (root / rel).stat().st_mtime_ns != OLD_MTIME_NS
            ]
            if changed:
                bad.append(f"--fix writes nothing ({argv[:1]}: {changed[:5]})")
            if code != 1:
                bad.append(f"--fix exits 1 when there are hits ({code})")
    return bad


# Each row is (path, text, the text after the patch is applied). One has no
# hit the patch suggests, so the patch must not name it.
PATCH_CASES = [
    ("a.md", "the colour here\n", "the color here\n"),  # spelling-ok
    ("docs/b.txt", "x\ncolour", "x\ncolor"),  # spelling-ok
    (
        "c.rst",
        "the grey\r\nand the centre\r\n",  # spelling-ok
        "the gray\r\nand the center\r\n",
    ),
    ("d.md", "page\x0cthe colour\nmore\n", "page\x0cthe color\nmore\n"),  # spelling-ok
    ("app/i18n/en.json", CATALOG_TEXT, CATALOG_WANT),
    ("e.md", "Colour Springs\n", "Colour Springs\n"),  # spelling-ok
]


def git_apply(patch: str, where: Path, *args: str) -> subprocess.CompletedProcess:
    # Outside any repository, git apply patches the files under `where`.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(where.parent)}
    return subprocess.run(
        ["git", "apply", *args],
        input=patch.encode("utf-8"),
        cwd=where,
        capture_output=True,
        check=False,
        env=env,
    )


def patch_applies(mod: ModuleType) -> list[str]:
    """The --fix patch says it is a suggestion, `git apply --check` accepts it
    on a copy of the files, and applying it makes exactly the expected text,
    while the files themselves are left as written."""
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        for rel, text, _ in PATCH_CASES:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(text.encode("utf-8"))
        code, patch, err = run_fix(
            mod, root, [str(root / r) for r, _, _ in PATCH_CASES]
        )
        header = mod.PATCH_HEADER
        if not patch.startswith(header) or "suggestion" not in header:
            bad.append(f"the patch's header says it is a suggestion ({patch[:200]!r})")
        if "nothing has been written" not in header:
            bad.append("the header says nothing has been written")
        if "a/e.md" in patch or "e.md:1:1" not in err:
            bad.append(f"a hit with no suggestion is listed, not patched ({err!r})")
        if code != 1:
            bad.append(f"--fix exits 1 when there are hits ({code})")
        if any((root / r).read_bytes() != t.encode("utf-8") for r, t, _ in PATCH_CASES):
            bad.append("--fix leaves the files as written")
        copy = Path(tmp) / "copy"
        shutil.copytree(root, copy)
        checked = git_apply(patch, copy, "--check")
        if checked.returncode != 0:
            bad.append(f"git apply --check takes the patch ({checked.stderr!r})")
            return bad
        applied = git_apply(patch, copy)
        wrong = [
            rel
            for rel, _, want in PATCH_CASES
            if (copy / rel).read_bytes() != want.encode("utf-8")
        ]
        if applied.returncode != 0 or wrong:
            bad.append(
                f"the patch makes the expected text ({wrong}, {applied.stderr!r})"
            )
    return bad


def named_files(mod: ModuleType) -> list[str]:
    """A file named twice (./a.md and a.md, or by a path through a symbolic link
    to a directory) is one file, and a named symbolic link to a file stands for
    its target, which gets one diff that `git apply --check` accepts, whether or
    not the target is named too; a link to no file is said to be skipped and
    makes the exit 1; a file outside the repository named by an absolute path or
    one that climbs ("..") is refused, said to be, and makes the exit 1, because
    `git apply` refuses such a path."""
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        (root / "sub").mkdir()
        target = root / "a.md"
        target.write_text(f"the {W} here\n", encoding="utf-8")
        link = root / "link.md"
        link.symlink_to(target)
        dirlink = root / "dirlink"
        dirlink.symlink_to(root / "sub")
        (root / "sub" / "b.md").write_text(f"the {W} there\n", encoding="utf-8")
        copy = Path(tmp) / "copy"
        shutil.copytree(root, copy, symlinks=True)
        cases = [
            ("the target and a link to it", [str(target), str(link)], 1),
            ("a link alone, its target not named", [str(link)], 1),
            ("the link first, then its target", [str(link), str(target)], 1),
            ("a path twice, with and without './'", [str(target), f"{root}/./a.md"], 1),
            (
                "a file by two paths, one through a linked directory",
                [str(root / "sub" / "b.md"), str(dirlink / "b.md")],
                1,
            ),
        ]
        for what, argv, want in cases:
            code, patch, err = run_fix(mod, root, argv)
            applied = git_apply(patch, copy, "--check")
            diffs = patch.count("diff --git")
            if diffs != want or applied.returncode != 0 or code != 1:
                bad.append(
                    f"--fix, {what}: {diffs} diff(s), "
                    f"git apply --check {applied.stderr!r}, exit {code}, {err!r}"
                )
            if mod.SYMLINK in err:
                bad.append(f"--fix, {what}, calls a link to a file skipped ({err!r})")
        saved = mod.ROOT
        mod.ROOT = root
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = mod.main([str(link), str(target)])
        finally:
            mod.ROOT = saved
        if code != 1 or err.getvalue().count("a.md:1:") != 1:
            bad.append(f"the check reports a file twice ({err.getvalue()!r})")

        gone = root / "gone.md"
        gone.symlink_to(root / "nowhere.md")
        code, patch, err = run_fix(mod, root, [str(gone)])
        if code != 1 or patch or mod.SYMLINK not in err:
            bad.append(f"--fix says a link to no file is skipped ({patch!r}, {err!r})")
        mod.ROOT = root
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = mod.main([str(gone)])
        finally:
            mod.ROOT = saved
        if code != 1 or mod.SYMLINK not in err.getvalue():
            bad.append(f"the check skips a link to no file ({err.getvalue()!r})")

        outside = Path(tmp) / "outside.md"
        outside.write_text(f"the {W} here\n", encoding="utf-8")
        for given in (str(outside), os.path.relpath(outside)):
            code, patch, err = run_fix(mod, root, [given])
            if code != 1 or patch or mod.OUTSIDE not in err:
                bad.append(
                    f"--fix refuses {given!r} outside the repository ({patch!r})"
                )
    return bad


# British by their shape, not listed: each is reported with the suggestion,
# and never in the patch (the verifier's third and fifth passes, #169). Each
# pattern of SHAPES has a word here that no other pattern matches.
SHAPED = [
    ("haematoxylin", "hematoxylin"),  # spelling-ok
    ("haematogenous", "hematogenous"),  # spelling-ok
    ("haemopoietic", "hemopoietic"),  # spelling-ok
    ("haemopericardium", "hemopericardium"),  # spelling-ok
    ("haemagglutination", "hemagglutination"),  # spelling-ok
    ("haemovigilance", "hemovigilance"),  # spelling-ok
    ("oesophagogastroduodenoscopy", "esophagogastroduodenoscopy"),  # spelling-ok
    ("oesophagogastric", "esophagogastric"),  # spelling-ok
    ("oestrogenised", "estrogenised"),  # spelling-ok
    ("foetoplacental", "fetoplacental"),  # spelling-ok
    ("foetomaternal", "fetomaternal"),  # spelling-ok
    ("paediatrist", "pediatrist"),  # spelling-ok
    ("anaesthesiometer", "anesthesiometer"),  # spelling-ok
    ("gynae", "gyne"),  # spelling-ok
    ("gynaeoid", "gyneoid"),  # spelling-ok
    ("acidaemia", "acidemia"),  # spelling-ok
    ("methaemoglobinaemia", "methemoglobinemia"),  # spelling-ok
    ("hyperbilirubinaemias", "hyperbilirubinemias"),  # spelling-ok
    ("isovolaemic", "isovolemic"),  # spelling-ok
    ("azotaemics", "azotemics"),  # spelling-ok
    ("otorrhoea", "otorrhea"),  # spelling-ok
    ("logorrhoeal", "logorrheal"),  # spelling-ok
    ("eupnoea", "eupnea"),  # spelling-ok
    ("platypnoeas", "platypneas"),  # spelling-ok
    ("hectolitre", "hectoliter"),  # spelling-ok
    ("hectolitres", "hectoliters"),  # spelling-ok
    ("methaemoglobin", "methemoglobin"),  # spelling-ok
    ("oedematogenic", "edematogenic"),  # spelling-ok
    ("tracheooesophageal", "tracheoesophageal"),  # spelling-ok
    ("polyoestrous", "polyestrous"),  # spelling-ok
    ("maternofoetal", "maternofetal"),  # spelling-ok
    ("faecolith", "fecolith"),  # spelling-ok
    ("caecum", "cecum"),  # spelling-ok
    ("logopaedics", "logopedics"),  # spelling-ok
    ("synaesthetic", "synesthetic"),  # spelling-ok
    ("pseudogynaecomastia", "pseudogynecomastia"),  # spelling-ok
    ("leucodystrophy", "leukodystrophy"),  # spelling-ok
    ("aetiopathogenesis", "etiopathogenesis"),  # spelling-ok
    ("palaeopathology", "paleopathology"),  # spelling-ok
    ("praecordial", "precordial"),  # spelling-ok
    ("pharmacopoeial", "pharmacopeial"),  # spelling-ok
    ("spirochaetal", "spirochetal"),  # spelling-ok
    ("sulphinpyrazone", "sulfinpyrazone"),  # spelling-ok
    ("antitumoural", "antitumoral"),  # spelling-ok
    ("otorrhoeas", "otorrheas"),  # spelling-ok
    ("eupnoeic", "eupneic"),  # spelling-ok
    ("glycaemically", "glycemically"),  # spelling-ok
    ("milligramme", "milligram"),  # spelling-ok
    # Each British leuco- stem, with a word no other pattern matches.
    ("leucocytoclastic", "leukocytoclastic"),  # spelling-ok
    ("leucopenias", "leukopenias"),  # spelling-ok
    ("leucotome", "leukotome"),  # spelling-ok
    ("leucotriene", "leukotriene"),  # spelling-ok
    ("leucopoiesis", "leukopoiesis"),  # spelling-ok
    ("leucoencephalopathy", "leukoencephalopathy"),  # spelling-ok
    ("leucaemogenic", "leukemogenic"),  # spelling-ok
    ("leukaemoid", "leukemoid"),  # spelling-ok
    ("leucoplakia", "leukoplakia"),  # spelling-ok
    ("leucoderma", "leukoderma"),  # spelling-ok
    # aesthe after each prefix.
    ("kinaesthetically", "kinesthetically"),  # spelling-ok
    ("paraesthetic", "paresthetic"),  # spelling-ok
    ("dysaesthetic", "dysesthetic"),  # spelling-ok
    ("hyperaesthetic", "hyperesthetic"),  # spelling-ok
    ("hypoaesthetic", "hypoesthetic"),  # spelling-ok
    ("hypaesthetic", "hypesthetic"),  # spelling-ok
    ("cenaesthesia", "cenesthesia"),  # spelling-ok
    # An oe- segment after each letter that may precede it.
    ("paraoesophageal", "paraesophageal"),  # spelling-ok
    ("antioedema", "antiedema"),  # spelling-ok
]
# Not reported: capitalized and not listed, a segment alone, hex, a Latin ending
# or epithet, an exception, a word the en_US dictionary accepts, or an American
# word that holds a segment's letters by accident (each narrowing of SHAPES).
NOT_SHAPED = [
    "Haemonetics",  # spelling-ok
    "Haematoxylin",  # spelling-ok
    "HAEMATOXYLIN",  # spelling-ok
    "Acidaemia",  # spelling-ok
    "aemia",  # spelling-ok
    "haem",  # spelling-ok
    "ACIDAEMIA",  # spelling-ok
    "haemolyticus",  # spelling-ok
    "haemophysalis",  # spelling-ok
    "haemolyticum",  # spelling-ok
    "gonorrhoeae",  # spelling-ok
    "paedomorphosis",
    "paedogenesis",
    "haemolyticusRate",  # spelling-ok
    "faecab",  # spelling-ok
    "caecilian",  # spelling-ok
    "caecilians",  # spelling-ok
    "leucotomy",  # spelling-ok
    "pharmacopoeia",  # spelling-ok
    "faecium",  # spelling-ok
    "haematobium",  # spelling-ok
    "haemofelis",  # spelling-ok
    "haemocanis",  # spelling-ok
    "haemominutum",  # spelling-ok
    # An -ensis epithet, constructed: no real one in the corpus has a British
    # shape, and LATIN_ENDINGS keeps one from being reported.
    "faecensis",  # spelling-ok
    "alphaemission",  # spelling-ok
    "videoedema",  # spelling-ok
    "phytoestrogen",  # spelling-ok
    "shoestring",  # spelling-ok
    "infoetl",  # spelling-ok
    "aesthetic",  # spelling-ok
    "unaesthetic",  # spelling-ok
    "programmed",  # spelling-ok
    "leucovorin",  # spelling-ok
    "gastroesophageal",  # spelling-ok
    "tracheoesophageal",  # spelling-ok
]


def shapes(mod: ModuleType) -> list[str]:
    bad = []
    found = scan(mod, [f"the {b} here" for b, _ in SHAPED])
    want = {n: [row] for n, row in enumerate(SHAPED, 1)}
    if found != want:
        wrong = {
            SHAPED[n - 1][0]: found.get(n) for n in want if found.get(n) != want[n]
        }
        bad.append(f"a British shape is reported, with its suggestion ({wrong})")
    text = "\n".join(f"the {b} here" for b, _ in SHAPED) + "\n"
    if suggested(mod, text) != text:
        bad.append("the patch leaves a word found by its shape")
    found = scan(mod, [f"the {w} here" for w in NOT_SHAPED])
    if found:
        bad.append(f"no shape matches {[NOT_SHAPED[n - 1] for n in found]}")
    return bad


# Not English: a word with an accented letter is not read, so neither its
# English-looking end nor its start is reported.
ACCENTED = [
    ("décentre", []),  # spelling-ok
    ("réanalyse", []),  # spelling-ok
    ("Décentre", []),  # spelling-ok
    ("centreé", []),  # spelling-ok
    ("a naïve colour", ["colour"]),  # spelling-ok
]


def accented(mod: ModuleType) -> list[str]:
    found = scan(mod, [line for line, _ in ACCENTED])
    got = {n: [w for w, _ in hits] for n, hits in found.items()}
    want = {n: words for n, (_, words) in enumerate(ACCENTED, 1) if words}
    return [] if got == want else [f"an accented word is not read ({got})"]


# Read as prose, though it looks like a URL or data: each British word is
# reported.
STILL_PROSE = [
    ("metadata:colour", ["colour"]),  # spelling-ok
    ("9ftp://host?colour", ["colour"]),  # spelling-ok
    ("aB1colour2cD3e=", ["colour"]),  # spelling-ok
    ("aB1colour2cD3eF=", []),  # spelling-ok
]


def still_prose(mod: ModuleType) -> list[str]:
    found = scan(mod, [line for line, _ in STILL_PROSE])
    got = {n: [w for w, _ in hits] for n, hits in found.items()}
    want = {n: words for n, (_, words) in enumerate(STILL_PROSE, 1) if words}
    return [] if got == want else [f"what is still prose is read ({got})"]


def is_text_window(mod: ModuleType) -> list[str]:
    """is_text() reads the first 1024 bytes: a NUL inside them makes a file
    binary, and one after them does not."""
    with tempfile.TemporaryDirectory() as tmp:
        inside = Path(tmp) / "inside.dat"
        inside.write_bytes(b"a" * 1000 + b"\x00")
        outside = Path(tmp) / "outside.dat"
        outside.write_bytes(b"a" * 1024 + b"\x00")
        ok = not mod.is_text(inside) and mod.is_text(outside)
    return [] if ok else ["is_text() reads exactly the first 1024 bytes"]


# The en_US Hunspell dictionary, pinned in pixi.toml: American English, with
# its affix rules expanded. No rule of the checker may match one of its
# lowercase words but these two, which it lists as variants and CLAUDE.md does
# not allow. The checker's DICTIONARY_WORDS are British-looking words the
# dictionary accepts ("leucotomy", "pharmacopoeia"), so they are not reported.
# Its capitalized entries that the checker lists (four surnames and places) are
# names, and a capitalized word is never in the suggestion patch.
DICTIONARY = Path(sys.prefix) / "share" / "hunspell_dictionaries" / "en_US"
CAUGHT_ON_PURPOSE = {"towards", "whilst"}  # spelling-ok


def hunspell_words(stem: Path) -> set[str]:
    """Every word of a Hunspell dictionary: its entries, and each entry with
    the affixes its flags allow (prefixes crossed with suffixes)."""
    affixes: dict[str, tuple[str, bool, list[tuple[str, str, re.Pattern[str]]]]] = {}
    lines = stem.with_suffix(".aff").read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        head = lines[i].split()
        if len(head) == 4 and head[0] in ("PFX", "SFX") and head[2] in ("Y", "N"):
            kind, flag, cross, count = head[0], head[1], head[2] == "Y", int(head[3])
            rules = []
            for rule in lines[i + 1 : i + 1 + count]:
                f = rule.split()
                strip = "" if f[2] == "0" else f[2]
                add = "" if f[3] == "0" else f[3].split("/")[0]
                anchored = f"^{f[4]}" if kind == "PFX" else f"{f[4]}$"
                rules.append((strip, add, re.compile(anchored)))
            affixes[flag] = (kind, cross, rules)
            i += count + 1
        else:
            i += 1
    words = set()
    entries = stem.with_suffix(".dic").read_text(encoding="utf-8").splitlines()[1:]
    for entry in entries:
        word, _, flags = entry.partition("/")
        words.add(word)
        suffixed = []
        for flag in flags:
            kind, cross, rules = affixes.get(flag, ("", False, []))
            for strip, add, condition in rules:
                if not condition.search(word):
                    continue
                if kind == "SFX" and word.endswith(strip):
                    new = word[: len(word) - len(strip)] + add
                    words.add(new)
                    if cross:
                        suffixed.append(new)
                elif kind == "PFX" and word.startswith(strip):
                    words.add(add + word[len(strip) :])
        for flag in flags:
            kind, cross, rules = affixes.get(flag, ("", False, []))
            if kind != "PFX" or not cross:
                continue
            for new in suffixed:
                for strip, add, condition in rules:
                    if condition.search(new) and new.startswith(strip):
                        words.add(add + new[len(strip) :])
    return words


AMERICAN_WORDS: list[str] = []


def american_words() -> list[str]:
    """The dictionary's words, expanded once per process (and shared with the
    mutants' processes, see share_words()), or [] if it is not installed."""
    if not AMERICAN_WORDS and DICTIONARY.with_suffix(".dic").exists():
        AMERICAN_WORDS.extend(sorted(hunspell_words(DICTIONARY)))
    return AMERICAN_WORDS


def share_words(words: list[str]) -> None:
    """A mutant process's initializer: the parent's expansion of the
    dictionary, so no process expands it again, whatever the start method."""
    AMERICAN_WORDS[:] = words


def dictionary(mod: ModuleType) -> list[str]:
    if not american_words():
        return [f"the en_US dictionary is installed ({DICTIONARY}.dic)"]
    # Each word as the checker reads it: its runs of letters ("pharmacopoeia's"
    # is "pharmacopoeia" and "s").
    matched = {
        w
        for w in AMERICAN_WORDS
        if w.islower()
        and any(
            mod.american(part) or mod.by_shape(part) for part in re.findall("[a-z]+", w)
        )
    }
    if matched != CAUGHT_ON_PURPOSE:
        return [f"no rule matches an American word ({sorted(matched)[:10]})"]
    return []


PROPERTIES = [
    every_word,
    table,
    ligatures,
    american_left_alone,
    capitalized,
    not_prose,
    corpus,
    python_protocol,
    slashes_in_prose,
    case_folding,
    spelling_ok,
    allowlist,
    unreadable,
    fixes,
    scanned,
    real_files_read,
    quoted_verbatim,
    translations,
    skip_dirs,
    fix_exit_codes,
    unopenable_is_text,
    corpus_skipped,
    fix_cases,
    fix_lines,
    file_kinds,
    catalog,
    fix_respects_skip,
    never_writes,
    patch_applies,
    binomials,
    shapes,
    accented,
    still_prose,
    is_text_window,
    named_files,
    dictionary,
]
# The two properties that read every word: a mutant reaches them only if every
# other property passed (see noticed()).
SLOWEST = (every_word, dictionary)


def run_properties(mod: ModuleType) -> list[str]:
    return [problem for prop in PROPERTIES for problem in prop(mod)]


def noticed(mod: ModuleType) -> list[str]:
    """The problems of the first property that fails on `mod`, trying the fast
    ones first. A mutant is noticed when any property fails, so once one has,
    the rest (every_word alone reads some 250,000 lines) would not change the
    verdict. The real checker runs every property (run_properties())."""
    fast = [prop for prop in PROPERTIES if prop not in SLOWEST]
    for prop in (*fast, *SLOWEST):
        problems = prop(mod)
        if problems:
            return problems
    return []


# ---------------------------------------------------------------------------
# The sections run against the real checker.
# ---------------------------------------------------------------------------


def decompositions(mod: ModuleType, word: str) -> list[tuple[str, str, str, str]]:
    """Every (family, prefix, stem, ending) that generates `word`."""
    out = []
    for family, (endings, prefixes, stems) in mod.FAMILIES.items():
        for prefix in prefixes:
            for stem in stems:
                for ending_b, _ in endings:
                    if prefix + stem + ending_b == word:
                        out.append((family, prefix, stem, ending_b))
    return out


# The endings of Latin epithets and genera, which no medical form may have.
LATIN_ENDINGS = ("alis", "ium", "icus", "ica", "ae", "ii", "um", "ensis")


def medical_decompositions(mod: ModuleType, word: str) -> list[tuple[str, str]]:
    """Every (stem, prefix) of MEDICAL that generates `word`."""
    return [
        (stem, prefix)
        for stem, _, endings, prefixes in mod.MEDICAL
        for prefix in prefixes
        for ending in endings
        if prefix + stem + mod.ending_pair(ending)[0] == word
    ]


def coverage() -> None:
    """The table is an independent account of the checker, so it must name every
    part of it. These read the checker's lists only to ask whether the table
    covers them; whether each row is caught is the table property's job."""
    print("The table covers every part of the checker")
    british = [w for w, _ in words_of(TABLE_ROWS)]
    explicit = {b for b, _ in TABLE_ROWS if b in cs.EXPLICIT}
    check(
        "every EXPLICIT word is in the table",
        explicit == set(cs.EXPLICIT),
        str(sorted(set(cs.EXPLICIT) - explicit)),
    )
    wrong = [b for b, a in TABLE_ROWS if b in cs.EXPLICIT and cs.EXPLICIT[b] != a]
    check("and the table agrees with EXPLICIT on each", not wrong, str(wrong))

    parts = [d for w in british for d in decompositions(cs, w)]
    for family, (endings, prefixes, stems) in cs.FAMILIES.items():
        used = [d for d in parts if d[0] == family]
        missing = [s for s in stems if s not in {d[2] for d in used}]
        check(f"{family}: a form of every stem", not missing, str(missing))
        missing = [e for e, _ in endings if e not in {d[3] for d in used}]
        check(f"{family}: a form of every ending", not missing, str(missing))
        missing = [p for p in prefixes if p not in {d[1] for d in used}]
        check(f"{family}: a form of every prefix", not missing, str(missing))
    medical = {d for w in british for d in medical_decompositions(cs, w)}
    missing = [m[0] for m in cs.MEDICAL if m[0] not in {d[0] for d in medical}]
    check("MEDICAL: a form of every stem", not missing, str(missing))
    # Of every stem with every one of its own prefixes: a prefix another row
    # also has ("non") would not be missed if it were dropped from this one.
    pairs = {(m[0], p) for m in cs.MEDICAL for p in m[3]}
    missing = sorted(pairs - medical)
    check("MEDICAL: a form of every stem with each prefix", not missing, str(missing))

    # A species epithet is never generated: no medical form has a Latin ending.
    generated = cs.generate({}, {}, cs.MEDICAL)
    latin = [w for w in generated if w.endswith(LATIN_ENDINGS)]
    check("MEDICAL generates no Latin epithet", not latin, str(latin[:5]))
    # A word is a run of letters, so hex is read as runs of a-f; no British word
    # may be made of those letters alone.
    hexlike = [w for w in cs.BRITISH if re.fullmatch("[a-f]+", w)]
    check("no British word can be read out of hex", not hexlike, str(hexlike))

    redundant = [
        w for w in cs.EXPLICIT if w in cs.generate(cs.FAMILIES, {}, cs.MEDICAL)
    ]
    check(
        "no EXPLICIT word is also generated, so dropping one is noticed",
        not redundant,
        str(redundant),
    )


def real_checker() -> None:
    print("The real checker")
    for prop in PROPERTIES:
        problems = prop(cs)
        check(prop.__name__.replace("_", " "), not problems, "; ".join(problems))
    check(
        "the word list is not trivially small",
        len(cs.BRITISH) > 500,
        str(len(cs.BRITISH)),
    )
    check(
        "#169: the plural that was missed is listed",
        cs.BRITISH.get("judgements") == "judgments",  # spelling-ok
    )


def skipping() -> None:
    print("What is skipped, and nothing else")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        british = "The colour.\n"  # spelling-ok
        names = [f"{d}/a.md" for d in sorted(cs.SKIP_DIRS)]
        near = [
            "sites/a.md",
            "builder/a.md",
            "website/a.md",
            "docs/build.md",
            "docs/site/notes.md" if "site" not in cs.SKIP_DIRS else "docs/sitemap.md",
            "my.git/a.md",
            "docs/a.md",
        ]
        for rel in names + near:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(british, encoding="utf-8")
        nested = root / "docs" / "node_modules" / "pkg" / "a.md"
        nested.parent.mkdir(parents=True)
        nested.write_text(british, encoding="utf-8")

        saved = cs.ROOT
        cs.ROOT = root
        try:
            found = {str(p.relative_to(root)) for p in cs.targets([])}
        finally:
            cs.ROOT = saved
        leaked = [n for n in names if n in found]
        check("every SKIP_DIRS directory is skipped", not leaked, str(leaked))
        check(
            "a SKIP_DIRS name nested deeper is skipped",
            "docs/node_modules/pkg/a.md" not in found,
        )
        missing = [n for n in near if n not in found]
        check("a name that only resembles one is checked", not missing, str(missing))

    for rel in sorted(cs.QUOTED_VERBATIM):
        check(f"quoted verbatim is skipped: {rel}", cs.skip(cs.ROOT / rel))
    for rel in [
        "data/other.json",
        "docs/frameworks/other.md",
        "docs/app/other.html",
        "app/js/10-frameworks/10-chai/06-other.js",
    ]:
        check(f"its neighbor is checked: {rel}", not cs.skip(cs.ROOT / rel))
    check("the checker itself is skipped", cs.skip(SCRIPT))
    check("the allowlist is skipped", cs.skip(ROOT / ".spelling-allow"))
    check(
        "its neighbor is checked: .spelling-allow.md",
        not cs.skip(ROOT / ".spelling-allow.md"),
    )
    check("this test is not skipped", not cs.skip(Path(__file__)))
    check(
        "a file outside the repository is checked",
        not cs.skip(Path(tempfile.gettempdir()) / "x.md"),
    )
    whole = {str(p.relative_to(ROOT)) for p in cs.targets([])}
    missing = [rel for rel in REAL if rel not in whole]
    check("a whole-repository run reads our own files", not missing, str(missing))
    problems = cs.check(Path(__file__), cs.load_allowlist())
    check("this test file passes its own checker", not problems, str(problems[:2]))


def command_line() -> None:
    print("The command")
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.md"
        good = Path(tmp) / "good.md"
        latin = Path(tmp) / "latin1.md"
        bad.write_text("Our judgements.\n", encoding="utf-8")  # spelling-ok
        good.write_text("Our judgments.\n", encoding="utf-8")
        latin.write_bytes("Our café.\n".encode("latin-1"))

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(SCRIPT), *args],
                capture_output=True,
                text=True,
                check=False,
                cwd=tmp,
            )

        hit = run(str(bad))
        check("a British spelling exits nonzero", hit.returncode == 1, hit.stderr)
        check("and names the file and the word", "bad.md:1:5" in hit.stderr, hit.stderr)
        clean = run(str(good))
        check("clean input exits zero", clean.returncode == 0, clean.stderr)
        both = run(str(good), str(bad))
        check("one bad file among good ones fails", both.returncode == 1)
        unread = run(str(latin))
        check(
            "a file that is not UTF-8 exits nonzero, and says so",
            unread.returncode == 1 and "UTF-8" in unread.stderr,
            unread.stderr,
        )
        unfixed = run("--fix", str(latin))
        check("--fix on a file it cannot read exits nonzero", unfixed.returncode == 1)
        clean = run("--fix", str(good))
        check(
            "--fix on clean input exits zero and prints no patch",
            clean.returncode == 0 and not clean.stdout,
            clean.stdout + clean.stderr,
        )
        before = bad.read_bytes()
        fix = run("--fix", "bad.md")
        check("--fix exits 1 on a hit", fix.returncode == 1, fix.stderr)
        check("--fix leaves the file as written", bad.read_bytes() == before)
        check(
            "--fix prints a suggestion patch, named from where it ran",
            fix.stdout.startswith(cs.PATCH_HEADER)
            and "--- a/bad.md" in fix.stdout
            and "+Our judgments." in fix.stdout,
            fix.stdout,
        )
        copy = Path(tmp) / "copy"
        copy.mkdir()
        shutil.copy(bad, copy / "bad.md")
        applied = git_apply(fix.stdout, copy)
        check(
            "and git apply makes the American text of a copy",
            applied.returncode == 0
            and (copy / "bad.md").read_text(encoding="utf-8") == "Our judgments.\n",
            applied.stderr.decode(errors="replace"),
        )
        check("the file itself still fails the check", run(str(bad)).returncode == 1)

        link = Path(tmp) / "link.md"
        link.symlink_to(bad)
        linked = run(str(link))
        check(
            "a named symbolic link to a file is checked as its target",
            linked.returncode == 1
            and "bad.md:1:" in linked.stderr
            and cs.SYMLINK not in linked.stderr,
            linked.stderr,
        )
        fix = run("--fix", "bad.md", "link.md")
        copy = Path(tmp) / "copy2"
        copy.mkdir()
        shutil.copy(bad, copy / "bad.md")
        applied = git_apply(fix.stdout, copy)
        check(
            "--fix with a link named patches its target once, and the patch applies",
            fix.stdout.count("diff --git") == 1
            and applied.returncode == 0
            and (copy / "bad.md").read_text(encoding="utf-8") == "Our judgments.\n",
            fix.stdout + applied.stderr.decode(errors="replace"),
        )
        fix = run("--fix", str(bad))
        check(
            "--fix refuses a file outside the repository named by an absolute path",
            fix.returncode == 1 and not fix.stdout and cs.OUTSIDE in fix.stderr,
            fix.stdout + fix.stderr,
        )

        name = Path(tmp) / "name.md"
        text = "Haemorrhage was noted; the colour too.\n"  # spelling-ok
        name.write_text(text, encoding="utf-8")
        hit = run(str(name))
        check(
            "a capitalized word is reported as not in the patch",
            hit.returncode == 1 and cs.LEFT_FOR_A_HUMAN in hit.stderr,
            hit.stderr,
        )
        fix = run("--fix", "name.md")
        check(
            "--fix suggests the lowercase word and lists the capitalized one",
            "+Haemorrhage was noted; the color too." in fix.stdout  # spelling-ok
            and f"name.md:1:1: {text.split()[0]!r}" in fix.stderr,
            fix.stdout + fix.stderr,
        )
        check(
            "and exits 1, leaving the file as written",
            fix.returncode == 1 and name.read_text(encoding="utf-8") == text,
        )

    print("A malformed .spelling-allow fails the command")
    code = malformed_allowlist_exit(cs)
    check("an unscoped allowlist line exits 1", code == 1, str(code))
    source = SCRIPT.read_text(encoding="utf-8")
    for n, (what, old, new) in enumerate(MALFORMED_MUTATIONS):
        check(f"mutation applies once: {what}", source.count(old) == 1, repr(old))
        mutant = load(source.replace(old, new), f"check_spelling_mutant_m{n}")
        code = malformed_allowlist_exit(mutant)
        check(f"noticed: {what}", code != 1, str(code))


def malformed_allowlist_exit(mod: ModuleType) -> int | str:
    """What main() returns, for a clean file, when .spelling-allow has a line with
    no glob."""
    with tempfile.TemporaryDirectory() as tmp:
        allow = Path(tmp) / ".spelling-allow"
        allow.write_text("cancelled()\n", encoding="utf-8")  # spelling-ok
        good = Path(tmp) / "good.md"
        good.write_text("Our judgments.\n", encoding="utf-8")
        saved = mod.ALLOWLIST
        mod.ALLOWLIST = allow
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return mod.main([str(good)])
        except Exception as error:  # a crash is reported, not passed
            return repr(error)
        finally:
            mod.ALLOWLIST = saved


# ---------------------------------------------------------------------------
# Mutation tests: break a copy of the checker, demand the properties notice.
# ---------------------------------------------------------------------------

# The source of patterns the mutations take apart.
PEDIATRIC_ROW_SOURCE = (
    '("paediatric", "pediatric", '  # spelling-ok
    '("", "s", "ian", "ians", "ally"), ("", "non"))'
)
OE_SOURCE = 'r"(?:^|(?<=[aioy]))(?:oedem|oesophag|oestr)"'
AESTHE_SOURCE = 'r"(?:an|kin|syn|par|dys|hyper|hypo|hyp|cen)aesthe"'
LEUCO_SOURCE = 'r"leuc(?:o(?:cyt|pen|dystroph|tom|trien|poie|encephal|plak|derm)|aem)"'
ENGLISH_FORM_SOURCE = 'r"(?:ia|oea|oma|itis|sis)$"'
DICTIONARY_WORDS_SOURCE = (
    'DICTIONARY_WORDS = ("leucotomy", "leucotomies", "pharmacopoeia", "pharmacopoeias")'
)


def drop_alternative(source: str, alt: str) -> str:
    """`source`, a pattern's text, with the alternative `alt` taken out of its
    group of alternatives."""
    for old, new in ((f"(?:{alt}|", "(?:"), (f"|{alt})", ")"), (f"|{alt}|", "|")):
        if old in source:
            return source.replace(old, new, 1)
    raise ValueError(f"{alt!r} is not an alternative of {source}")


MUTATIONS: list[tuple[str, str, str]] = [
    # (what is broken, text in the checker, replacement)
    ("a root is dropped", '"behavi",', ""),  # spelling-ok
    ("an explicit word is dropped", '"judgement": "judgment",', ""),  # spelling-ok
    ("'aluminium' is dropped", '"aluminium": "aluminum",', ""),  # spelling-ok
    ("'whilst' is dropped", '"whilst": "while",', ""),  # spelling-ok
    ("'ageing' is dropped", '"ageing": "aging",', ""),  # spelling-ok
    (
        "a MEDICAL stem is dropped",
        '    ("faec", "fec", ("es", "al", "aloma", "alith", "aliths"), ("",)),\n',
        "",
    ),
    ("an -aemia stem is dropped", '    ("anaem", "anem", AEMIA, ("", "non")),\n', ""),
    (
        "a MEDICAL prefix is dropped",
        '("glycaem", "glycem", AEMIA, ("", "hypo", "hyper", "normo", "eu"))',
        '("glycaem", "glycem", AEMIA, ("", "hyper", "normo", "eu"))',
    ),
    (
        # The prefix another row also has: only the patch notices, since the
        # word is still found by its shape.
        "the paediatric row's 'non' is dropped",  # spelling-ok
        PEDIATRIC_ROW_SOURCE,
        PEDIATRIC_ROW_SOURCE.replace('("", "non"))', '("",))'),
    ),
    (
        "a MEDICAL British ending is not respelled",
        "= prefix + stem_a + ending_a",
        "= prefix + stem_a + ending_b",
    ),
    (
        "MEDICAL prefixes are not generated",
        "        for prefix in prefixes:\n            for ending in endings:",
        "        for prefix in prefixes[:1]:\n            for ending in endings:",
    ),
    (
        "a Latin ending is generated",
        '("faec", "fec", ("es",',
        '("faec", "fec", ("alis", "ium", "es",',
    ),
    (
        "a MEDICAL stem matches inside a longer word",
        "    return BRITISH.get(word.lower().translate(LIGATURES))",
        "    key = word.lower().translate(LIGATURES)\n"
        "    hit = BRITISH.get(key)\n"
        "    for stem_b, stem_a, _, _ in MEDICAL:\n"
        "        if hit is None and stem_b in key:\n"
        "            hit = key.replace(stem_b, stem_a)\n"
        "    return hit",
    ),
    ("the -yse stem 'catal' is dropped", '            "catal",\n', ""),
    ("the -ise stem 'immun' is dropped", '"immun",', ""),
    ("the -our stem 'ferv' is dropped", '"ferv",', ""),
    ("the -re stem 'scept' is dropped", '"scept",', ""),
    ("the ending -ourise is dropped", '("ourise", "orize"),', ""),  # spelling-ok
    (
        "the ending -isational is dropped",
        '("isational", "izational"),',
        "",
    ),  # spelling-ok
    ("the ending -llist is dropped", '("list", "ist"),', ""),
    ("the -ce prefix 'sub' is dropped", '("", "sub"),', '("",),'),
    # A new stem that generates an American word must be noticed.
    ("the -ise stem 'prec' is added", '"priorit",', '"priorit", "prec",'),
    ("the -ll stem 'compel' is added", '"counsel",', '"counsel", "compel",'),
    ("the -re stem 'lust' is added", '"lit",', '"lit", "lust",'),
    (
        "case folding is off",
        "BRITISH.get(word.lower().translate",
        "BRITISH.get(word.translate",
    ),
    (
        "ligatures are not read",
        "BRITISH.get(word.lower().translate(LIGATURES))",
        "BRITISH.get(word.lower())",
    ),
    (
        "ligatures are not letters",
        'WORD = re.compile(r"[A-ZŒÆ]+(?![a-zœæ])|[A-ZŒÆ]?[a-zœæ]+")',
        'WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")',
    ),
    ("spelling-ok is ignored", "if MARKER in line:", "if False:"),
    (
        "any mention of spelling exempts a line",
        "if MARKER in line:",
        'if MARKER.split("-")[0] in line:',
    ),
    ("the allowlist is ignored", "for phrase in allow:", "for phrase in ():"),
    (
        "an allowed phrase exempts its whole line",
        "for phrase in allow:",
        "for phrase in ([] if any(p in line for p in allow) else allow):",
    ),
    (
        "an allowed phrase matches in any case",
        'scannable = scannable.replace(phrase, " " * len(phrase))',
        "scannable = re.sub(re.escape(phrase), blank, scannable, flags=re.I)",
    ),
    (
        "an allowlist glob is ignored",
        "for glob, phrase in allow if where.match(glob)]",
        "for glob, phrase in allow]",
    ),
    (
        "an unscoped allowlist line is accepted",
        "if not sep or not glob or not phrase.strip():",
        "if False:",
    ),
    (
        "inflections are not generated",
        "for ending_b, ending_a in endings",
        "for ending_b, ending_a in endings[:1]",
    ),
    (
        "prefixes are not generated",
        "            for prefix in prefixes:\n                for ending_b",
        "            for prefix in prefixes[:1]:\n                for ending_b",
    ),
    (
        "identifiers are not split",
        "WORD.finditer(scannable, run.start(), run.end())",
        "WHOLE.finditer(scannable, run.start(), run.end())",
    ),
    (
        "text that is not prose is not blanked",
        "scannable = blank_unprose(scannable)",
        "scannable = scannable",
    ),
    (
        "any run with a slash is a path",
        'if path.startswith(("./", "../", "~/", "/")) or any(',
        "if True or any(",
    ),
    (
        "a file that is not UTF-8 is passed in silence",
        "except UnicodeDecodeError as error:\n        return [",
        "except UnicodeDecodeError as error:\n        return [] if True else [",
    ),
    ("the patch ignores case", "return american.upper()", "return american"),
    # Which files a whole-repository run reads.
    (
        "only known suffixes are read",
        "and is_text(p)",
        'and p.suffix in {".md", ".py", ".js", ".json", ".yml", ".toml"}',
    ),
    (
        "a binary file is read",
        "return not head.translate(None, TEXT_BYTES)",
        "return True",
    ),
    ("a symbolic link is read", "and not p.is_symlink()", ""),
    ("app/ is a SKIP_DIRS directory", '"backups",', '"backups", "app",'),
    (
        "docs/developing.md is quoted verbatim",
        '"docs/app/index.html",',
        '"docs/app/index.html", "docs/developing.md",',
    ),
    (
        "en.json is treated as a translation",
        '\n        and parts[2] != f"{Locale.EN}.json"',
        "",
    ),
    (
        "a translation is any path with a catalog's name in it",
        "len(parts) == 3",
        "len(parts) >= 3",
    ),
    (
        "QUOTED_VERBATIM grows",
        '"docs/app/index.html",',
        '"docs/app/index.html", "README.md",',
    ),
    # URLs and paths.
    ("a URL runs to the end of the line", r'[\w+.-]*://\S+"', r'[\w+.-]*://.*"'),
    ("a colon makes a URL", r'[\w+.-]*://\S+"', r'[\w+.-]*:\S+"'),
    (
        "email addresses are read",
        "(URL, EMAIL, DIGEST, DOMAIN)",
        "(URL, DIGEST, DOMAIN)",
    ),
    (
        "domains are read",
        "(URL, EMAIL, DIGEST, DOMAIN)",
        "(URL, EMAIL, DIGEST)",
    ),
    (
        "file names are read",
        "    line = FILE_NAME.sub(blank, line)\n",
        "",
    ),
    (
        "digests are read",
        "(URL, EMAIL, DIGEST, DOMAIN)",
        "(URL, EMAIL, DOMAIN)",
    ),
    ("encoded data is read", "return ENCODED.sub(blank_encoded, line)", "return line"),
    (
        "padding is not a sign of data",
        '    if run.endswith("="):\n        return True',
        '    if run.endswith("="):\n        pass',
    ),
    (
        "an identifier with a digit is taken for data",
        "return runs * 2 >= len(alnum)",
        "return runs * 3 >= len(alnum)",
    ),
    (
        "only the most broken-up data is taken for data",
        "return runs * 2 >= len(alnum)",
        "return runs >= len(alnum)",
    ),
    (
        "the trailing period of a path is read as its extension's",
        'path = run.rstrip(".")',
        "path = run",
    ),
    # What the patch suggests, and what it leaves for a person.
    (
        "a capitalized word is suggested",
        "    if not word.islower():\n        return Left.CAPITALIZED\n",
        "",
    ),
    (
        "the report does not say what the patch leaves",
        'f"{left_note(reason)}\\n"',
        'f"\\n"',
    ),
    # The files read.
    (
        "the corpus is not skipped",
        "        or PurePosixPath(rel).parent.as_posix() == CORPUS\n",
        "",
    ),
    (
        "anything under the corpus is skipped",
        "PurePosixPath(rel).parent.as_posix() == CORPUS",
        "rel.startswith(CORPUS)",
    ),
    (
        "an escape byte makes a file binary",
        "{7, 8, 9, 10, 11, 12, 13, 27}",
        "{7, 8, 9, 10, 11, 12, 13}",
    ),
    ("a DEL byte is text", " - {0x7F}", ""),
    (
        "a file is_text() cannot open is binary",
        "    except OSError:\n        return True",
        "    except OSError:\n        return False",
    ),
    ("build/ is not skipped", '    "build",\n', ""),
    (
        "a run with no digit is taken for encoded data",
        "    if not any(c.isdigit() for c in alnum):\n        return False\n",
        "",
    ),
    ("a domain's path is read", r"""(?:[/:?#][^\s)\]>\"'`]*)?""", ""),
    ("the path of a git address is read", r"(?:\.[\w-]+)+(?::\S*)?", r"(?:\.[\w-]+)+"),
    ("-aemias is not generated", '("ia", "ias", "ic")', '("ia", "ic")'),  # spelling-ok
    ("a -pnoea word's -ic is not generated", '("a", "as", "ic")', '("a", "as")'),
    (
        "any dot is a file extension",
        r'EXTENSION = re.compile(r"\w\.[A-Za-z0-9]+$")',
        r'EXTENSION = re.compile(r"\.")',
    ),
    (
        "a dot and a word anywhere is a file extension",
        r'EXTENSION = re.compile(r"\w\.[A-Za-z0-9]+$")',
        r'EXTENSION = re.compile(r"\.[A-Za-z0-9]+$")',
    ),
    # The allowlist.
    (
        "an allowlist glob also matches the file's name",
        "if where.match(glob)]",
        "if where.match(glob) or where.match(PurePosixPath(glob).name)]",
    ),
    (
        "an allowed phrase is blanked word by word",
        "    for phrase in allow:\n",
        "    for phrase in [w for p in allow for w in p.split()]:\n",
    ),
    (
        "an allowed phrase is compared in lowercase",
        'scannable = scannable.replace(phrase, " " * len(phrase))',
        'scannable = scannable.replace(phrase.lower(), " " * len(phrase))',
    ),
    (
        "relative() gives the file's name",
        "return resolved.relative_to(ROOT).as_posix()",
        "return resolved.name",
    ),
    (
        "a file that cannot be read is passed in silence",
        'return [f"{path}: could not be read',
        'return [] if True else [f"{path}: could not be read',
    ),
    (
        "the marker is read in any case",
        "if MARKER in line:",
        "if MARKER in line.lower():",
    ),
]

BEFORE_SOURCE = """BEFORE = frozenset("([\\"'*")"""
AFTER_SOURCE = """AFTER = frozenset(")]\\"'*,;:.!?")"""
MUTATIONS += [
    # Each pattern of SHAPES, dropped.
    *[(f"the shape {p} is dropped", f'    r"{p}",\n', "") for p in cs.SHAPES],
    # A character that may stand next to a word the patch suggests, added or
    # dropped.
    *[
        (
            f"{c!r} may stand before a word the patch suggests",
            BEFORE_SOURCE,
            BEFORE_SOURCE[:-2] + c + '")',
        )
        for c in "_-@:.=<`~#0"
    ],
    *[
        (
            f"{c!r} may stand after a word the patch suggests",
            AFTER_SOURCE,
            AFTER_SOURCE[:-2] + c + '")',
        )
        for c in "_-/@=<`~#(0"
    ],
    ("'(' may not stand before", BEFORE_SOURCE, BEFORE_SOURCE.replace('"([', '"[', 1)),
    ("'.' may not stand after", AFTER_SOURCE, AFTER_SOURCE.replace(".", "", 1)),
    (
        "--fix ignores skip()",
        "            elif path.is_file() and not skip(path):\n                name =",
        "            elif path.is_file():\n                name =",
    ),
    (
        "column 0 reads the end of the line",
        "LEAD.search(line[:start])",
        "LEAD.search(line[:start] or line[-1:])",
    ),
    (
        "a URL needs no boundary",
        r'r"(?<![A-Za-z0-9])[A-Za-z][\w+.-]*://\S+"',
        r'r"[A-Za-z][\w+.-]*://\S+"',
    ),
    (
        "a URL's boundary is a word boundary",
        r'r"(?<![A-Za-z0-9])[A-Za-z][\w+.-]*://\S+"',
        r'r"\b[A-Za-z][\w+.-]*://\S+"',
    ),
    (
        "a scheme without slashes needs no boundary",
        'rf"|(?<![A-Za-z0-9])(?:{',
        'rf"|(?:{',
    ),
    (
        "a scheme without slashes has a word boundary",
        'rf"|(?<![A-Za-z0-9])(?:{',
        r'rf"|\b(?:{',
    ),
    *[
        (
            f"{w}: is not a scheme",
            "{'|'.join(SCHEMES)}",
            "{'|'.join(s for s in SCHEMES if s != '" + w + "')}",
        )
        for w in cs.SCHEMES
    ],
    *[
        (
            f"{w} is not a top-level domain",
            "{'|'.join(TLDS)}",
            "{'|'.join(t for t in TLDS if t != '" + w + "')}",
        )
        for w in cs.TLDS
    ],
    (".caddy is not a file extension", "|otf|env|caddy)", "|otf|env)"),
    (
        "library is not a code word",
        'frozenset({"import", "require", "library"})',
        'frozenset({"import", "require"})',
    ),
    (
        "a fence may not be indented",
        'FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")',
        'FENCE = re.compile(r"(`{3,}|~{3,})")',
    ),
    (
        "a binomial reads a ligature as another letter",
        "    key = word.translate(LIGATURES)\n    if not word.islower()",
        "    key = word\n    if not word.islower()",
    ),
    (
        "a genus name may follow a letter",
        'r"(?:(?<![A-Za-z])([A-Z][a-z]+)|',
        'r"(?:([A-Z][a-z]+)|',
    ),
    (
        "an initial may follow a letter",
        "(?<![^\\s*_\\\"'(\\[])([A-Z])",
        "([A-Z])",
    ),
    (
        "the words that are no genus are ignored",
        "titled.group(1).lower() not in NOT_GENUS_WORDS",
        "True",
    ),
    (
        "a never-epithet is an epithet",
        " or key in NOT_EPITHETS",
        "",
    ),
    (".lock is not a file extension", "|conf|lock|", "|conf|"),
    ("md5 is not a digest", "|sha512|md5)", "|sha512)"),
    ("encoded data needs 24 characters", "{16,}", "{24,}"),
    ("encoded data needs 17 characters", "{16,}", "{17,}"),
    ("encoded data needs 15 characters", "{16,}", "{15,}"),
    (
        "~ is not a path character",
        r'SLASHED = re.compile(r"[\w.~-]*/[\w./~-]*")',
        r'SLASHED = re.compile(r"[\w.-]*/[\w./-]*")',
    ),
    ("~/ does not start a path", '("./", "../", "~/", "/")', '("./", "../", "/")'),
    ("../ does not start a path", '("./", "../", "~/", "/")', '("./", "~/", "/")'),
    (
        "the patch respells a line left to right",
        "in reversed(found):",
        "in found:",
    ),
    (
        "oesophagi is not generated",  # spelling-ok
        '            "us",\n            "i",\n            "eal",',
        '            "us",\n            "eal",',
    ),
    (
        "is_text() reads 512 bytes",
        "head = handle.read(1024)",
        "head = handle.read(512)",
    ),
    (
        "is_text() reads 2048 bytes",
        "head = handle.read(1024)",
        "head = handle.read(2048)",
    ),
    (
        "BEL, BS, VT and FF make a file binary",
        "{7, 8, 9, 10, 11, 12, 13, 27}",
        "{9, 10, 13, 27}",
    ),
    # Words with an accent.
    (
        "accented letters are not letters",
        'LETTERS = re.compile(r"[^\\W\\d_]+")',
        'LETTERS = re.compile(r"[A-Za-zŒÆœæ]+")',
    ),
    (
        "a word with an accent is read",
        "        if not ENGLISH.issuperset(run.group(0)):\n            continue\n",
        "",
    ),
    # Shapes.
    (
        "a word found by its shape is suggested",
        "    if not listed:\n        return Left.SHAPE\n",
        "",
    ),
    (
        "a shape is matched in any case",
        "    if not word.islower():\n        return None\n",
        "",
    ),
    (
        "a Latin ending is matched by shape",
        "            latin\n            or key in LATIN_EPITHETS",
        "            False\n            or key in LATIN_EPITHETS",
    ),
    (
        "a Latin epithet is matched by shape",
        "            or key in LATIN_EPITHETS\n",
        "",
    ),
    (
        "the dictionary's words are matched",
        "            or key in DICTIONARY_WORDS\n",
        "",
    ),
    ("hex is matched by shape", "            or HEX.fullmatch(key)\n", ""),
    (
        "a segment alone is a shape",
        "if match is None or match.group(0) == key:",
        "if match is None:",
    ),
    ("-ous is a Latin ending", " and not key.endswith(NOT_LATIN)", ""),
    (
        "gynae is not a shape",  # spelling-ok
        'SHAPE_WORDS = ("gynae",)',  # spelling-ok
        "SHAPE_WORDS = ()",
    ),
    # Each narrowing of a pattern, undone, matches an American word.
    ("haem matches anywhere", 'r"^haem|haem(?=[ao])"', 'r"haem"'),
    (
        "an oe- segment matches after any letter",
        OE_SOURCE,
        'r"(?:oedem|oesophag|oestr)"',
    ),
    (
        "an oe- segment matches after an e",
        OE_SOURCE,
        OE_SOURCE.replace("[aioy]", "[aeioy]"),
    ),
    ("foet matches anywhere", 'r"foet(?=al|us|id|o|icid)"', 'r"foet"'),
    ("aesthe matches after any letter", AESTHE_SOURCE, 'r"(?<=.)aesthe"'),
    ("aesthe matches after two letters", AESTHE_SOURCE, 'r"(?<=..)aesthe"'),
    ("gramme matches anywhere", 'r"grammes?$"', 'r"grammes?"'),  # spelling-ok
    ("leuco matches in any word", LEUCO_SOURCE, 'r"leuco|leucaem"'),
    ("the shape leuc is added", LEUCO_SOURCE, 'r"leuc"'),
    # Each part of a narrowed pattern, dropped: a British word only it matches
    # is missed.
    *[
        (
            f"an oe- segment no longer matches after {c!r}",
            OE_SOURCE,
            OE_SOURCE.replace(c, "", 1),
        )
        for c in "aioy"
    ],
    *[
        (
            f"the oe- segment {alt} is dropped",
            OE_SOURCE,
            drop_alternative(OE_SOURCE, alt),
        )
        for alt in ("oedem", "oesophag", "oestr")
    ],
    *[
        (
            f"aesthe after {alt} is dropped",
            AESTHE_SOURCE,
            drop_alternative(AESTHE_SOURCE, alt),
        )
        for alt in ("an", "kin", "syn", "par", "dys", "hyper", "hypo", "hyp", "cen")
    ],
    *[
        (
            f"the leuco stem {alt} is dropped",
            LEUCO_SOURCE,
            drop_alternative(LEUCO_SOURCE, alt),
        )
        for alt in (
            "cyt",
            "pen",
            "dystroph",
            "tom",
            "trien",
            "poie",
            "encephal",
            "plak",
            "derm",
            "aem",
        )
    ],
    # Each word excepted from the shapes, and each Latin epithet and dictionary
    # word, dropped: the word is reported.
    *[(f"{w} is no longer excepted", f'    "{w}",\n', "") for w in cs.SHAPE_EXCEPTIONS],
    *[
        (
            f"{w} is no longer a Latin epithet",
            f'    "{w}",\n',
            "",
        )
        for w in cs.LATIN_EPITHETS
    ],
    *[
        (
            f"{w} is no longer a dictionary word",
            DICTIONARY_WORDS_SOURCE,
            DICTIONARY_WORDS_SOURCE.replace(f'"{w}", ', "").replace(f', "{w}"', ""),
        )
        for w in cs.DICTIONARY_WORDS
    ],
    ("-ensis is not a Latin ending", '"icum", "ensis")', '"icum")'),
    # The binomial skip.
    (
        "the binomial skip is off",
        "    if genus is None:\n        return False\n",
        "    return False\n",
    ),
    (
        "any capitalized word is a genus",
        "return genus.group(1) in GENERA",
        "return genus.group(1) is not None",
    ),
    (
        "an abbreviation is no genus",
        "    if genus.group(2) is None:\n",
        "    if True:\n",
    ),
    (
        "an English ending is an epithet",
        'EPITHET_ENDINGS = ("a", ',
        'EPITHET_ENDINGS = ("al", "a", ',
    ),
    (
        "-ous is an epithet",
        " or key.endswith(NOT_LATIN):\n        return False\n    if ENGLISH",
        ":\n        return False\n    if ENGLISH",
    ),
    # Only a true Latin epithet is skipped (the verifier's seventh pass).
    (
        "an English medical form is an epithet",
        "ENGLISH_FORM.search(key) or ",
        "",
    ),
    *[
        (
            f"-{alt} is not an English form",
            ENGLISH_FORM_SOURCE,
            drop_alternative(ENGLISH_FORM_SOURCE, alt),
        )
        for alt in ("ia", "oea", "oma", "itis", "sis")
    ],
    (
        "a listed word is an epithet",
        "return key not in BRITISH or key in LISTED_EPITHETS",
        "return True",
    ),
    (
        "the listed epithet is not an epithet",
        'LISTED_EPITHETS = ("foetus",)',  # spelling-ok
        "LISTED_EPITHETS = ()",
    ),
    # A symbolic link named on the command line, and a file outside the
    # repository the patch cannot name.
    (
        "a link to no file is read by --fix",
        '            if path.is_symlink():\n                print(f"  skipped',
        '            if False:\n                print(f"  skipped',
    ),
    (
        "a link to no file is read by the check",
        '        if path.is_symlink():\n            print(f"skipped',
        '        if False:\n            print(f"skipped',
    ),
    (
        "a link to no file is passed in silence by the check",
        '{SYMLINK}", file=sys.stderr)\n            unread += 1\n',
        '{SYMLINK}", file=sys.stderr)\n',
    ),
    (
        "a file named twice is read twice",
        "        if real not in seen:\n",
        "        if True:\n",
    ),
    (
        "a named link stands for itself, not its target",
        "        if path.is_symlink() and real.is_file():\n",
        "        if False:\n",
    ),
    (
        "an absolute path outside is named in the patch",
        "if path.is_absolute() or ",
        "if ",
    ),
    ("a path that climbs is named in the patch", ' or ".." in path.parts:', ":"),
    (
        "a file the patch cannot name is passed in silence",
        '{OUTSIDE}", file=sys.stderr)\n                    unread += 1\n',
        '{OUTSIDE}", file=sys.stderr)\n',
    ),
    ("markup hides the genus", 'text = MARKUP.sub(" ", before)', "text = before"),
    (
        "the genus is not read on the line before",
        'text = MARKUP.sub(" ", previous) + " " + text',
        "text = text",
    ),
    (
        "a blank line does not end a binomial",
        "        previous = line\n",
        "        previous = line if line.strip() else previous\n",
    ),
    ("a comma is markup", '\\[\\]]*$"\n)\n# The word', '\\[\\],]*$"\n)\n# The word'),
    # Nothing is written, and the patch is one git applies.
    (
        "--fix writes the file",
        "                elif after != before:\n                    patches.append",
        "                elif after != before:\n"
        '                    path.write_text(after, encoding="utf-8")\n'
        "                    patches.append",
    ),
    (
        "the patch has no header",
        'print(PATCH_HEADER + "".join(patches), end="")',
        'print("".join(patches), end="")',
    ),
    (
        "--fix exits 0 with hits",
        "return 1 if unread or patches or hand else 0",
        "return 1 if unread else 0",
    ),
    (
        "--fix does not list the rest",
        '                hand.extend(f"  {name or path}:{hit}" for hit in left)\n',
        "",
    ),
    (
        "a last line with no newline is not marked",
        'else f"{line}\\n{NO_NEWLINE}"',
        'else f"{line}\\n"',
    ),
    (
        "the patch splits lines as Python does",
        "        GIT_LINE.findall(before),\n        GIT_LINE.findall(after),",
        "        before.splitlines(keepends=True),\n"
        "        after.splitlines(keepends=True),",
    ),
    (
        "line endings are translated when read",
        'return path.read_bytes().decode("utf-8")',
        'return path.read_text(encoding="utf-8")',
    ),
    (
        "an abbreviation is a file extension",
        " and not DOTTED.fullmatch(segment)",
        "",
    ),
    # The kinds of file the patch suggests in.
    (
        "a .py file is prose",
        'PROSE_SUFFIXES = {".md": Kind.MARKDOWN,',
        'PROSE_SUFFIXES = {".py": Kind.TEXT, ".md": Kind.MARKDOWN,',
    ),
    ("a suffix is read in its case", "path.suffix.lower()", "path.suffix"),
    (
        "the catalog is not prose",
        "    if relative(path) == CATALOG:\n",
        "    if False:\n",
    ),
    (
        "a catalog's key is prose",
        "        if not value or not value.start(1) <= start < end <= value.end(1):",
        "        if not value:",
    ),
    (
        "any line of the catalog is prose",
        "        if not value or not value.start(1) <= start < end <= value.end(1):",
        "        if False:",
    ),
    # Code in prose.
    (
        "a line of code is prose",
        "    elif code or in_code(line, start):",
        "    elif in_code(line, start):",
    ),
    ("a command is prose", "    if CODE_LINE.match(line):\n        return True\n", ""),
    (
        "inline code is prose",
        "    return any(span.start() <= start < span.end() for span in spans)",
        "    return False",
    ),
    ("a fence opens nothing", "                self.fence = fence.group(1)\n", ""),
    (
        "a fence never closes",
        '                    self.fence = ""\n',
        "                    pass\n",
    ),
    ("a shorter fence closes a longer one", "len(mark) >= len(self.fence)", "True"),
    (
        "an indented Markdown line is prose",
        "            return bool(INDENTED.match(line))",
        "            return False",
    ),
    (
        "a literal block is prose",
        'if directive or line.rstrip().endswith("::"):',
        "if directive:",
    ),
    (
        "a code directive is prose",
        "directive = bool(RST_CODE.match(line))",
        "directive = False",
    ),
    (
        "import is prose",
        "    if word_before(line, start).strip(",
        "    if False and word_before(line, start).strip(",
    ),
]

# main() refusing a malformed .spelling-allow, broken: these are run by
# command_line(), which calls main() itself.
MALFORMED_MUTATIONS = [
    (
        "a malformed allowlist exits zero",
        "        print(error, file=sys.stderr)\n        return 1\n",
        "        print(error, file=sys.stderr)\n        return 0\n",
    ),
    (
        "a malformed allowlist is read as empty",
        "        allow = load_allowlist()\n",
        "        allow = []\n",
    ),
]


def run_mutant(n: int) -> tuple[list[str], str]:
    """The problems the properties find in mutant `n`, or the error it raised."""
    _, old, new = MUTATIONS[n]
    source = SCRIPT.read_text(encoding="utf-8")
    mutant = load(source.replace(old, new), name=f"check_spelling_mutant_{n}")
    try:
        return noticed(mutant), ""
    except Exception as error:  # a crash is not a mutation worth the name
        return [], repr(error)


def mutations() -> None:
    print("Mutation tests: a broken checker is noticed")
    source = SCRIPT.read_text(encoding="utf-8")
    applies = [source.count(old) == 1 for _, old, _ in MUTATIONS]
    for (what, old, _), present in zip(MUTATIONS, applies, strict=True):
        check(f"mutation applies once: {what}", present, f"{old!r} not once")
    # Each mutant runs every property over every word, so they run in parallel.
    todo = [n for n, present in enumerate(applies) if present]
    with ProcessPoolExecutor(
        initializer=share_words, initargs=(american_words(),)
    ) as pool:
        results = list(pool.map(run_mutant, todo))
    for n, (problems, error) in zip(todo, results, strict=True):
        what = MUTATIONS[n][0]
        if error:
            check(f"the mutant runs: {what}", False, error)
            continue
        check(f"noticed: {what}", bool(problems), "every property still passed")

    mutant = load(
        source.replace("        rel in QUOTED_VERBATIM\n        or ", "        "),
        "check_spelling_mutant_q",
    )
    check(
        "the QUOTED_VERBATIM mutation applies",
        source.count("        rel in QUOTED_VERBATIM\n        or ") == 1,
    )
    quoted = sorted(cs.QUOTED_VERBATIM)[0]
    check("the real checker skips a quoted file", cs.skip(ROOT / quoted))
    check("noticed: QUOTED_VERBATIM ignored", not mutant.skip(ROOT / quoted))
    mutant = load(
        source.replace("if resolved == SELF:", "if False:"),
        "check_spelling_mutant_s",
    )
    check(
        "noticed: the checker no longer skips itself",
        not mutant.skip(mutant.SELF),
    )
    mutant = load(
        source.replace("if resolved == ALLOWLIST.resolve():", "if False:"),
        "check_spelling_mutant_a",
    )
    check(
        "noticed: the allowlist is no longer skipped",
        not mutant.skip(ROOT / ".spelling-allow"),
    )


def main() -> int:
    real_checker()
    coverage()
    skipping()
    command_line()
    mutations()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("spelling guardrail checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
