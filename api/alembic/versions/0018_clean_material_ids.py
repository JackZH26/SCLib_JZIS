"""Clean ``$/_/{/}`` from materials.id and re-target bookmarks.

Revision ID: 0018_clean_material_ids
Down revision: 0017_final_strip_all_markup

After 0017 cleared display columns, 576 material primary keys still
carried LaTeX scaffolding (e.g. ``mat:li$x($c$2$h$8$n$2$)$y$fe$2$se$2$``).
This migration renames them to their stripped form.

Tricky bits handled in one PL/pgSQL DO block (race-free, atomic):

* **Twin merge.** When a dirty id cleans to a target that already
  exists, append the dirty row's ``records`` array onto the target
  and DELETE the dirty row instead of UPDATE-ing the primary key.
* **Cascading dirty→dirty.** When two dirty ids clean to the same
  target, the second iteration sees the first one's rename and
  takes the merge branch. Sequential FOR-LOOP processing makes
  this implicit.
* **Bookmark preservation.** Users may have ``bookmarks.target_id``
  pointing at a soon-to-be-renamed material. The block first wipes
  per-user duplicate bookmarks (where the user happens to have BOTH
  the dirty and clean id saved) so the subsequent re-target UPDATE
  doesn't violate the ``(user_id, target_type, target_id)``
  uniqueness index, then re-targets the survivors.

The Python-loop migrations 0014/0015 tried this and partially
failed during a crash-loop deploy; pure SQL inside a DO block is
both more reliable and runs entirely server-side, no driver-level
quoting headaches.
"""
from alembic import op
from sqlalchemy import text


revision = "0018_clean_material_ids"
down_revision = "0017_final_strip_all_markup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1: drop bookmarks where the user already saved both the
    # dirty id and its cleaned twin. The re-target UPDATE in step 2
    # would otherwise crash on the unique (user_id, target_type,
    # target_id) constraint.
    bind.execute(text(r"""
        DELETE FROM bookmarks b1
        USING bookmarks b2
        WHERE b1.target_type = 'material'
          AND b1.target_id ~ '[$_{}]'
          AND b2.user_id = b1.user_id
          AND b2.target_type = 'material'
          AND b2.target_id = REPLACE(REPLACE(REPLACE(REPLACE(
                b1.target_id, '$', ''), '_', ''), '{', ''), '}', '')
          AND b2.id != b1.id;
    """))

    # Step 2: re-target the surviving bookmarks before we touch
    # materials, so a user with a dirty-id bookmark gets pointed at
    # the cleaned material rather than orphaned by step 3.
    bind.execute(text(r"""
        UPDATE bookmarks
        SET target_id = REPLACE(REPLACE(REPLACE(REPLACE(
            target_id, '$', ''), '_', ''), '{', ''), '}', '')
        WHERE target_type = 'material'
          AND target_id ~ '[$_{}]';
    """))

    # Step 3: rename material ids in a server-side loop.
    bind.execute(text(r"""
        DO $do$
        DECLARE
            r       RECORD;
            new_id  TEXT;
        BEGIN
            FOR r IN
                SELECT id, records
                FROM materials
                WHERE id ~ '[$_{}]'
                ORDER BY id           -- deterministic, easier to debug
            LOOP
                new_id := REPLACE(REPLACE(REPLACE(REPLACE(
                    r.id, '$', ''), '_', ''), '{', ''), '}', '');
                IF new_id = r.id THEN
                    CONTINUE;
                END IF;
                IF EXISTS (SELECT 1 FROM materials WHERE id = new_id) THEN
                    -- Append this row's records onto the existing
                    -- twin. JSONB || merges by concatenation; the
                    -- aggregator's next sweep dedupes by
                    -- (paper_id, year, tc) at the materials-table
                    -- summary level so the surface stays sane.
                    UPDATE materials
                    SET records = records || r.records
                    WHERE id = new_id;
                    DELETE FROM materials WHERE id = r.id;
                ELSE
                    UPDATE materials SET id = new_id WHERE id = r.id;
                END IF;
            END LOOP;
        END
        $do$;
    """))


def downgrade() -> None:
    pass
