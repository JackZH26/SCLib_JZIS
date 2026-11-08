"""Derived C-collation keysets; retain all original v1 rows and functions."""
import sqlalchemy as sa

INDEXES=(('idx_retrieval_legacy_keyset_v2','index_generation_members','generation_id'),
         ('idx_retrieval_content_keyset_v2','retrieval_content_members_v2','content_id'))


def register(metadata):
    result={}
    for name,relation,parent in INDEXES:
        table=metadata.tables[relation]
        result[name]=sa.Index(name,table.c[parent],table.c.vector_id.collate('C'))
    return result
