# Original Discovery input decks

These four files were copied byte-for-byte from the prior native QE 7.5 local
captures. They are not reconstructed test inputs. Their independent SHA-256
pins are the execution/initialization file entries in the matching manifests
under `frontend/tests/fixtures/qe-output`:

| Input | Existing preparation manifest | Manifest file role |
|---|---|---|
| `scf.in` | `scf.json` | execution |
| `relax.in` | `relax.json` | execution |
| `initialization.in` | `initialization.json` | initialization |
| `relax-initialization.in` | `relax-initialization.json` | initialization |

The native XML and stdout remain in that existing fixture directory. Full UPF
files are not redistributed. Unit tests use synthetic header-only files;
separate private replay uses the original, manifest-pinned PS Library bytes.
Neither source labels nor numerical convergence certify a physical material.
