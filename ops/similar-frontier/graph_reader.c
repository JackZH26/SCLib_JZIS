/* Offline-only entry point. The original, unmodified HNSW AM owns traversal. */
#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "access/genam.h"
#include "access/amapi.h"
#include "catalog/namespace.h"
#include "commands/defrem.h"
#include "parser/parse_func.h"
#include "utils/lsyscache.h"
#include "nodes/makefuncs.h"
#include "miscadmin.h"
#include "access/relscan.h"
#include "access/table.h"
#include "executor/executor.h"
#include "utils/rel.h"
#include "utils/snapmgr.h"
#include "utils/memutils.h"

PG_MODULE_MAGIC;
PG_FUNCTION_INFO_V1(sclib_frontier_graph_stream);

typedef struct {
    Relation heap;
    Relation index;
    IndexScanDesc scan;
} GraphCursor;

static void
close_graph(Datum context)
{
    GraphCursor *cursor = (GraphCursor *) DatumGetPointer(context);
    index_endscan(cursor->scan);
    table_close(cursor->heap, AccessShareLock);
    index_close(cursor->index, AccessShareLock);
}

Datum
sclib_frontier_graph_stream(PG_FUNCTION_ARGS)
{
    FuncCallContext *func;
    GraphCursor *cursor;
    ItemPointer found;
    ItemPointer value;
    ReturnSetInfo *out = (ReturnSetInfo *) fcinfo->resultinfo;

    if (SRF_IS_FIRSTCALL()) {
        MemoryContext previous;
        ScanKeyData order;
        Datum query;

        func = SRF_FIRSTCALL_INIT();
        previous = MemoryContextSwitchTo(func->multi_call_memory_ctx);
        Oid schema = get_namespace_oid("sclib_private_carrier", false);
        Oid index_oid = get_relname_relid("sealed_hnsw", schema);
        Oid heap_oid = get_relname_relid("carrier", schema);
        Oid vector_type = get_fn_expr_argtype(fcinfo->flinfo, 0);
        Oid parameters[2] = {vector_type, vector_type};
        Oid distance_oid = LookupFuncName(list_make2(makeString("public"), makeString("cosine_distance")),
                                          2, parameters, false);
        /* No user-controlled relation, access method or support function. The SQL bootstrap
         * revokes schema writes and PUBLIC execute and grants only the private build role. */
        if (!OidIsValid(index_oid) || !OidIsValid(heap_oid))
            elog(ERROR, "sealed scratch graph is missing");
        query = PointerGetDatum(PG_DETOAST_DATUM_COPY(PG_GETARG_DATUM(0)));
        cursor = palloc0(sizeof(GraphCursor));
        cursor->index = index_open(index_oid, AccessShareLock);
        if (cursor->index->rd_rel->relam != get_index_am_oid("hnsw", false) ||
            cursor->index->rd_index == NULL || !cursor->index->rd_index->indisvalid ||
            !cursor->index->rd_index->indisready || cursor->index->rd_index->indrelid != heap_oid ||
            cursor->index->rd_index->indnkeyatts != 1 ||
            TupleDescAttr(RelationGetDescr(cursor->index), 0)->atttypid != vector_type ||
            TupleDescAttr(RelationGetDescr(cursor->index), 0)->atttypmod != 768)
            elog(ERROR, "sealed scratch graph identity mismatch");
        cursor->heap = table_open(heap_oid, AccessShareLock);
        ScanKeyEntryInitialize(&order, SK_ORDER_BY, 1, 1, InvalidOid, InvalidOid, distance_oid, query);
        cursor->scan = index_beginscan(cursor->heap, cursor->index, GetActiveSnapshot(), 0, 1);
        index_rescan(cursor->scan, NULL, 0, &order, 1);
        /* The callback runs before the SRF context is freed, including on a normal early CLOSE.
         * PostgreSQL's resource owner handles transaction aborts. */
        RegisterExprContextCallback(out->econtext, close_graph, PointerGetDatum(cursor));
        func->user_fctx = cursor;
        MemoryContextSwitchTo(previous);
    }
    func = SRF_PERCALL_SETUP();
    cursor = func->user_fctx;
    CHECK_FOR_INTERRUPTS();
    found = index_getnext_tid(cursor->scan, ForwardScanDirection);
    if (found == NULL) {
        UnregisterExprContextCallback(out->econtext, close_graph, PointerGetDatum(cursor));
        close_graph(PointerGetDatum(cursor));
        SRF_RETURN_DONE(func);
    }
    value = palloc(sizeof(ItemPointerData));
    *value = *found;
    SRF_RETURN_NEXT(func, PointerGetDatum(value));
}
