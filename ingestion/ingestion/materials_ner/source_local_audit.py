"""Display each lexical occurrence beside its own original source context."""
from . import source_mentions as base
from .contract import canonical,digest
from .evidence import source_catalog
from .inventory import source_text

VERSION='materials-mention-local-context/1'
PROMPT_VERSION='materials-source-local-audit-prompt/1.0.0'
REPAIR_PROMPT_VERSION='materials-source-local-audit-repair-prompt/1.0.0'
AUDIT_VERSION=base.AUDIT_VERSION
MentionAudit=base.MentionAudit
mention_manifest=base.mention_manifest
output_schema=base.output_schema
validate_audit=base.validate_audit

INSTRUCTIONS="""Each NUMERIC_OCCURRENCE below has an immutable ID, literal numeric text and
its own exact local source context. Read THAT occurrence before assigning its kind.
Do not reconstruct IDs by counting numbers in the document or reuse a nearby
number's explanation. Equal tokens at different coordinates may have different
scientific meanings. The context is a display aid, not an additional source or
reference answer; use the full TARGET/CONTEXT blocks for sentence continuations.
The lexical token may include punctuation from the source; its shape alone does
not determine whether it is a citation, value, formula, unit or figure label.
Audit later repeated or approximate assertions as well as initial endpoints.
Do not infer that a statement belongs to the next named phase or to a nearby
sample. An unresolved scientific association is allowed in a source item; do not
invent phase labels in sample_raw. Preserve attribution for cited structural
findings relevant to the superconducting material, and qualitative assertions.
The result-item inventory and occurrence decisions must describe the same source.
"""
PROMPT_HASH=digest({'version':PROMPT_VERSION,'base':base.PROMPT_HASH,
                    'local_context':VERSION,'radius':100,'instructions':INSTRUCTIONS})
REPAIR_PROMPT_HASH=digest({'version':REPAIR_PROMPT_VERSION,'base':PROMPT_HASH,
                          'instructions':base.REPAIR_INSTRUCTIONS,'item_diagnostics':1})


def local_context(bundle):
    manifest=mention_manifest(bundle);blocks={b.id:b for b in bundle.blocks};rows=[]
    for mention in manifest['mentions']:
        block=blocks[mention['block_id']]
        a=max(0,mention['start_char']-100);b=min(len(block.text),mention['end_char']+100)
        rows.append(dict(mention,context_start_char=a,context_end_char=b,
            context_quote=block.text[a:b],left_context=block.text[a:mention['start_char']],
            right_context=block.text[mention['end_char']:b]))
    return {'schema':VERSION,'bundle_sha256':manifest['bundle_sha256'],
        'mention_manifest_sha256':digest(manifest),'radius_characters':100,'occurrences':rows,
        'contains_scientific_labels':False,'baseline_included':False}


def item_diagnostics(previous,bundle):
    candidate=MentionAudit.model_validate(previous)
    manifest=mention_manifest(bundle);catalog=source_catalog(bundle)
    return [{'item_id':item.id,'value_raw':item.value_raw,'source_span_ids':item.source_span_ids,
        'literal_possible_mention_ids':sorted(base.item_mentions(item,catalog,manifest)),
        'linked_mention_ids':[d.mention_id for d in candidate.mention_decisions if item.id in d.item_ids],
        'literal_matches_do_not_establish_scientific_meaning':True} for item in candidate.items]


def compare_inventory(candidate,inventory,graph,bundle):
    """Keep textual assertions pending even when value_raw is not null."""
    comparison=base.compare_inventory(candidate,inventory,graph,bundle)
    comparison['schema']='materials-source-audit-comparison/2'
    comparison['qualitative_items_requiring_semantic_comparison']=[
        item.model_dump() for item in candidate.items
        if item.value_raw is None or not any(ch.isnumeric() for ch in item.value_raw)]
    return comparison


def render(bundle):
    context=local_context(bundle)
    lines=[base.INSTRUCTIONS,INSTRUCTIONS,source_text(bundle)]
    # The complete literal ledger is frozen separately. The displayed occurrence
    # omits repeated hashes, but its exact coordinates and text are unmodified.
    for row in context['occurrences']:
        shown={k:row[k] for k in ['id','block_id','span_ids','start_char','end_char','text','left_context','right_context']}
        lines.append('NUMERIC_OCCURRENCE: '+canonical(shown))
    return '\n'.join(lines+['MENTION_MANIFEST_SHA256: '+context['mention_manifest_sha256'],
        'LOCAL_CONTEXT_SHA256: '+digest(context),'Return '+AUDIT_VERSION+'.'])


def render_repair(bundle,previous,validation):
    return '\n'.join([render(bundle),base.REPAIR_INSTRUCTIONS,'PREVIOUS_SOURCE_AUDIT: '+canonical(previous),
        'ACCOUNTING_DIAGNOSTICS: '+canonical(validation),
        'ITEM_LINK_DIAGNOSTICS: '+canonical(item_diagnostics(previous,bundle)),'Return '+AUDIT_VERSION+'.'])
