"""Shared semantic planning checks; these rules never infer facts for the model."""

RELATION_RULES = """For cross-entity or cross-stage explanations, distinguish the entity,
the state/value it owns or stores, and the action performed on that state. A box named
"saved value" is insufficient if its owner and the referenced object's identity are
unclear. Show ownership/reference with explicit node wording or a labelled edge.
Keep earlier/stored and later/recomputed values distinct: name whose state each is,
what changes, and which TWO values are compared. A change to one entity does not
silently update a copy/reference stored by another entity. Make the comparison result
and the actor who detects or acts on it visible when supported by source_text.
Every action edge must have unambiguous subject, object, direction and source support;
spatial adjacency or a generic arrow does not explain storage, comparison or detection.
Use kind=flow for supported order and kind=network for references/ownership that do
not form a sequence. Do not force these roles into a three-column transformation.
Alternatively use a table with explicit entity/state/action columns when it explains
the same source facts more clearly. Use separate full-size panels for distinct facts,
and repeat explicit entity names across panels rather than relying on hidden links.
These are questions to resolve from the source, NOT a required five-step mechanism:
include only applicable, source-supported roles. Do not invent a storage location,
comparison algorithm, detector or temporal order absent from the source. If the
source leaves a role unspecified, keep that limit explicit instead of filling it in.
Preserve the full narration and source-grounded applications when choosing panels.
"""

RELATION_REVIEW_RULES = """Check cross-entity/state relationships against BOTH source_text
and actual visible labels/edges/table cells. Identify who stores whose state, whether
a stored reference and a recomputed/current value are distinguished, which two values
are compared, what a change affects, and who detects the discrepancy, WHERE the source
supports those roles. Verify direction and ownership, not just the presence of words.
Do not infer a missing relationship from the title, narration or background knowledge.
A technically correct generic chain can still omit the source's cross-entity mechanism.
Report wrong ownership/direction or invented mechanics as factual_error, and missing
source-supported roles as missing_content; neither is a cosmetic/readability issue.
Do not demand a mechanism or actor the source does not specify. These checks do not
establish truth mechanically; the screenshot and source review must still decide.
"""
