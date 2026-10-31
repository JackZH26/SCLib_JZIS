"""Validate a bounded official arXiv Atom response without changing source bytes."""
import re
from urllib.parse import parse_qs, urlencode, urlsplit
import xml.etree.ElementTree as ET


ATOM = '{http://www.w3.org/2005/Atom}'
ARXIV = '{http://arxiv.org/schemas/atom}'
IDENTIFIER = r'(?:[A-Za-z][A-Za-z.-]*/[0-9]{7}|[0-9]{4}\.[0-9]{4,5})'
WITHDRAWN = re.compile(
    r'(?:this (?:paper|article|submission) (?:has been|is|was) withdrawn|arxiv:withdrawn)', re.I)


def metadata_url(ids):
    if (not 1 <= len(ids) <= 60 or len(set(ids)) != len(ids)
            or any(not re.fullmatch(IDENTIFIER, aid) for aid in ids)):
        raise ValueError('official_metadata_invalid_id_list')
    return 'https://export.arxiv.org/api/query?' + urlencode(
        {'id_list': ','.join(ids), 'max_results': len(ids)})


def requested_ids(receipt):
    url = receipt.get('requested_url', '')
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    ids = query.get('id_list', [''])[0].split(',')
    if (receipt.get('status') != 200 or receipt.get('final_url') != url
            or parsed.scheme != 'https' or parsed.netloc != 'export.arxiv.org'
            or parsed.path != '/api/query' or parsed.fragment
            or set(query) != {'id_list', 'max_results'}
            or query.get('max_results') != [str(len(ids))]
            or query.get('id_list') != [','.join(ids)]):
        raise ValueError('official_batch_metadata_request_mismatch')
    metadata_url(ids)
    return ids


def parse_metadata(receipt, raw):
    ids = set(requested_ids(receipt))
    if len(raw) > 4 * 1024**2:
        raise ValueError('official_batch_metadata_byte_bound')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('official_batch_metadata_invalid_xml') from exc
    if root.tag != ATOM + 'feed':
        raise ValueError('official_batch_metadata_feed_required')
    results = {}
    for entry in root.findall(ATOM + 'entry'):
        entry_id = entry.findtext(ATOM + 'id', '').strip()
        match = re.fullmatch(r'https?://arxiv\.org/abs/(' + IDENTIFIER + r')(v[1-9][0-9]*)', entry_id)
        if not match:
            raise ValueError('official_batch_metadata_entry_identity')
        aid, version = match.groups()
        if aid not in ids or aid in results:
            raise ValueError('official_batch_metadata_extra_or_duplicate_identity')
        own_text = '\n'.join(entry.findtext(tag, '') for tag in (
            ATOM + 'title', ATOM + 'summary', ARXIV + 'comment', ARXIV + 'journal_ref'))
        results[aid] = {'version': version, 'withdrawn': bool(WITHDRAWN.search(own_text))}
    return results
