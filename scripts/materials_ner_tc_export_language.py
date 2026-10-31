"""Check structured export text while preserving verbatim source quotations."""
import json
import re


CJK = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')


def check_structured(value):
    if CJK.search(json.dumps(value, ensure_ascii=False)):
        raise ValueError('cjk_in_structured_export_field')


def check_records(records, *, source_evidence=False):
    original_quotes_with_cjk = 0
    for record in records:
        structured = dict(record)
        if source_evidence:
            structured['evidence'] = []
            for evidence in record.get('evidence', []):
                item = dict(evidence)
                quote = item.pop('quote', '')
                original_quotes_with_cjk += bool(CJK.search(quote))
                structured['evidence'].append(item)
        check_structured(structured)
    return original_quotes_with_cjk


def check_csv_rows(filename, fieldnames, rows):
    check_structured(fieldnames)
    original_quotes_with_cjk = 0
    for row in rows:
        # Private host paths are forbidden in all downloadable cells, including quotes.
        raw = json.dumps(row, ensure_ascii=False)
        if '/Users/' in raw or '/var/folders/' in raw:
            raise ValueError('private_path_in_export')
        structured = dict(row)
        if filename == 'materials_evidence.csv':
            quote = structured.pop('quote', '')
            original_quotes_with_cjk += bool(CJK.search(quote))
        check_structured(structured)
    return original_quotes_with_cjk
