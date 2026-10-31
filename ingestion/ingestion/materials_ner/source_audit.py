"""Bounded original-file structure inventory, without executing or editing TeX.

Roots, dependency targets, supplement names and identity tokens are review
candidates. They never certify paper roles, publication versions or completeness.
No source text is removed from an existing bundle by this inspection.
"""
from collections import Counter,defaultdict
import gzip
import io
from pathlib import Path,PurePosixPath
import posixpath
import re
import tarfile

from .contract import digest
from .sources import MAX_SOURCE_BYTES,sha,verify_bundle

VERSION='materials-original-source-audit/1'
MAX_MEMBERS=10000
MAX_TEXT_MEMBER=8*1024*1024
MAX_ARCHIVE_BYTES=256*1024*1024
TEXT_SUFFIXES={'.tex','.txt','.bbl','.bib','.sty','.cls'}
PARSER_SUFFIXES={'.tex','.txt','.bbl'}
GRAPHICS_SUFFIXES=('.pdf','.eps','.ps','.png','.jpg','.jpeg','.svg')
COMMAND=re.compile(r'\\(input|include|includegraphics|includepdf|bibliography)\*?\s*(?:\[[^\]\n]*\]\s*)?\{([^{}]*)\}')
DEPENDENCY_TOKEN=re.compile(r'\\(?:input|include|includegraphics|includepdf|bibliography|subfile|import|subimport|epsfig|epsfbox)\b')
ROOT=re.compile(r'\\(?:documentclass|documentstyle)(?:\s*\[[^]]*\])?\s*\{')
ARXIV=re.compile(r'arXiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(v[1-9]\d*)?',re.I)


def _safe_name(name):
    path=PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '..' not in path.parts and not any(ord(c)<32 for c in name)


def _mask_comments(text):
    """Mask percent comments while preserving every source character offset."""
    chars=list(text);start=0
    for line in text.splitlines(keepends=True):
        for index,char in enumerate(line):
            if char!='%':continue
            backslashes=0;position=index-1
            while position>=0 and line[position]=='\\':backslashes+=1;position-=1
            if backslashes%2:continue
            for j in range(index,len(line)):
                if line[j] not in '\r\n':chars[start+j]=' '
            break
        start+=len(line)
    return ''.join(chars)


def _token_candidates(text,locator,work_id):
    expected=work_id.removeprefix('arxiv:')
    return [dict(locator=locator,start_char=m.start(),end_char=m.end(),literal=m.group(),
        matches_expected_work=m[1]==expected,version_candidate=m[2],
        publication_version_verified=False) for m in ARXIV.finditer(text)]


def _targets(name,argument,kind,names):
    if not argument or any(c in argument for c in '\\{}#$') or not _safe_name(argument):
        return [],'nonliteral_or_unsafe_reference'
    bases={posixpath.normpath(argument),posixpath.normpath(posixpath.join(posixpath.dirname(name),argument))}
    extensions=('', '.tex') if kind in {'input','include'} else ('','.bbl','.bib') if kind=='bibliography' else ('',*GRAPHICS_SUFFIXES)
    found=sorted({base+ext for base in bases for ext in extensions if base+ext in names})
    return found,'one_literal_candidate' if len(found)==1 else 'ambiguous_candidates' if found else 'not_resolved_by_literal_lookup'


def audit_source(path: Path,*,work_id: str,bundle=None):
    """Inventory exact source bytes and optional existing parser representation."""
    if not work_id.startswith('arxiv:'):raise ValueError('source_audit_requires_arxiv_work')
    raw=Path(path).read_bytes()
    if not raw or len(raw)>MAX_SOURCE_BYTES:raise ValueError('source_audit_byte_bound')
    checksum=sha(raw);holds={'publication_version_unverified','scientific_source_roles_unreviewed',
        'visual_and_supplement_coverage_unreviewed'}
    result=dict(schema=VERSION,work_id=work_id,source_sha256=checksum,source_bytes=len(raw),
        source_modified=False,source_text_removed=False,scientific_acceptance=False,
        publication_version_verified=False,full_paper_coverage_verified=False,
        limitation='Literal structure candidates only; no macro execution, publication-role assignment or scientific qualification.')
    if bundle is not None:
        verify_bundle(bundle)
        if bundle.work_id!=work_id or any(d.source_sha256!=checksum for d in bundle.documents):
            raise ValueError('source_audit_bundle_binding_mismatch')
        result['bundle']=dict(sha256=digest(bundle.model_dump()),documents=len(bundle.documents),blocks=len(bundle.blocks),
            characters=sum(len(b.text) for b in bundle.blocks),declared_coverages=[d.coverage for d in bundle.documents])
    if raw.startswith(b'%PDF'):
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:raise ValueError('source_audit_encrypted_pdf')
        pages=[];tokens=[]
        by_page={b.locator:b for b in bundle.blocks} if bundle else {}
        for index,page in enumerate(reader.pages,1):
            block=by_page.get(f'pdf_page:{index}')
            # A standalone inspection records geometry only. Supplied parser
            # blocks are audited without running a second competing extractor.
            text=block.text if block is not None else None
            pages.append(dict(page=index,width_points=float(page.mediabox.width),height_points=float(page.mediabox.height),
                rotation=page.rotation,extracted_characters=len(text) if text is not None else None,
                text_nonempty=bool(text.strip()) if text is not None else None,
                visual_review_completed=False))
            if index==1 and text is not None:tokens+=_token_candidates(text,block.locator,work_id)
        result.update(container='pdf',pages=pages,identity_token_candidates=tokens,
            page_text_count_matches_bundle=len(by_page)==len(pages) if bundle else None)
        if any(p['text_nonempty'] is False for p in pages):holds.add('pdf_page_without_recovered_text')
        if any(p['rotation'] for p in pages):holds.add('pdf_rotation_requires_visual_review')
        result['hold_codes']=sorted(holds);return result
    members=[];texts={};total=0;archive_bytes=0
    if tarfile.is_tarfile(io.BytesIO(raw)):
        container='tar'
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
            for index,member in enumerate(archive):
                if index>=MAX_MEMBERS:raise ValueError('source_audit_member_bound')
                archive_bytes+=member.size
                if member.size<0 or archive_bytes>MAX_ARCHIVE_BYTES:raise ValueError('source_audit_archive_expansion_bound')
                name=posixpath.normpath(member.name);safe=_safe_name(member.name)
                entry=dict(index=index,name=member.name,normalized_name=name,safe_relative_name=safe,
                    declared_bytes=member.size,regular_file=member.isfile(),link=member.issym() or member.islnk())
                suffix=PurePosixPath(name).suffix.lower()
                entry['legacy_parser_selected']=member.isfile() and suffix in PARSER_SUFFIXES
                if not safe:holds.add('unsafe_archive_path')
                if entry['link']:holds.add('archive_link_requires_review')
                if member.isfile() and suffix in TEXT_SUFFIXES and safe:
                    total+=member.size
                    if member.size>MAX_TEXT_MEMBER or total>MAX_SOURCE_BYTES:raise ValueError('source_audit_expanded_text_bound')
                    data=archive.extractfile(member).read(MAX_TEXT_MEMBER+1)
                    if len(data)!=member.size:raise ValueError('source_audit_member_size_mismatch')
                    entry['sha256']=sha(data)
                    try:
                        text=data.decode('utf-8',errors='strict');entry['utf8_decodable']=True
                        if suffix in {'.tex','.txt'}:texts[index]=(name,text)
                    except UnicodeDecodeError:
                        entry['utf8_decodable']=False;holds.add('text_encoding_requires_explicit_review')
                members.append(entry)
    elif raw.startswith(b'\x1f\x8b'):
        container='gzip_text'
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as source:data=source.read(MAX_SOURCE_BYTES+1)
        if len(data)>MAX_SOURCE_BYTES:raise ValueError('source_audit_expanded_text_bound')
        entry=dict(index=0,name='gzip_member:0',normalized_name='gzip_member:0',safe_relative_name=True,
            declared_bytes=len(data),regular_file=True,link=False,legacy_parser_selected=True,sha256=sha(data))
        try:texts[0]=(entry['name'],data.decode('utf-8',errors='strict'));entry['utf8_decodable']=True
        except UnicodeDecodeError:entry['utf8_decodable']=False;holds.add('text_encoding_requires_explicit_review')
        members.append(entry)
    else:
        container='text';data=raw
        try:texts[0]=('text:0',data.decode('utf-8',errors='strict'));decodable=True
        except UnicodeDecodeError:decodable=False;holds.add('text_encoding_requires_explicit_review')
        members.append(dict(index=0,name='text:0',normalized_name='text:0',safe_relative_name=True,
            declared_bytes=len(data),regular_file=True,link=False,legacy_parser_selected=True,sha256=sha(data),utf8_decodable=decodable))
    names={m['normalized_name'] for m in members if m['regular_file'] and m['safe_relative_name']}
    paths=Counter(m['normalized_name'] for m in members)
    duplicate_paths=sorted(n for n,c in paths.items() if c>1)
    if duplicate_paths:holds.add('duplicate_archive_member_path')
    roots=[];edges=[];identity=[];unsupported=[];by_hash=defaultdict(list)
    for m in members:
        if m.get('sha256'):by_hash[m['sha256']].append(m['index'])
    for index,(name,text) in texts.items():
        masked=_mask_comments(text)
        if ROOT.search(masked) and re.search(r'\\begin\s*\{document\}',masked):roots.append(dict(member_index=index,name=name))
        matches=list(COMMAND.finditer(masked));matched_starts={m.start() for m in matches}
        for match in matches:
            command,argument=match.groups()
            arguments=argument.split(',') if command=='bibliography' else [argument]
            for value in arguments:
                targets,status=_targets(name,value.strip(),command,names)
                edges.append(dict(member_index=index,member_name=name,command=command,argument=value.strip(),
                    start_char=match.start(),end_char=match.end(),literal=text[match.start():match.end()],
                    target_candidates=targets,resolution=status))
        unsupported += [dict(member_index=index,start_char=m.start(),command=m.group())
            for m in DEPENDENCY_TOKEN.finditer(masked) if m.start() not in matched_starts]
        identity+=_token_candidates(text,name,work_id)
    if len(roots)!=1:holds.add('main_file_candidates_ambiguous_or_missing')
    if any(e['resolution']!='one_literal_candidate' for e in edges):holds.add('tex_dependencies_require_review')
    if unsupported:holds.add('unsupported_tex_dependency_syntax')
    # An included PDF may contain the paper itself, not just a plotted figure.
    # A valid TeX wrapper and a resolved file path do not establish page coverage.
    # Preserve the dependency for explicit page extraction and role review.
    if any(e['command']=='includepdf' for e in edges) or any(
            e['command']==r'\includepdf' for e in unsupported):
        holds.add('embedded_pdf_requires_page_extraction_and_role_review')
    # No main/root selection and no exclusion is applied automatically.
    result.update(container=container,members=members,archive_declared_member_bytes=archive_bytes if container=='tar' else len(data),
        root_candidates=roots,dependency_candidates=edges,
        unsupported_dependency_tokens=unsupported,duplicate_member_paths=duplicate_paths,
        identical_text_member_groups=[dict(sha256=h,member_indices=ids) for h,ids in sorted(by_hash.items()) if len(ids)>1],
        supplement_name_candidates=[m['index'] for m in members if re.search(r'(?:supp(?:lement)?|(?:^|[_./-])sm(?:[_./-]|$))',m['name'],re.I)],
        identity_token_candidates=identity,roles_auto_assigned=False,hold_codes=sorted(holds))
    return result
