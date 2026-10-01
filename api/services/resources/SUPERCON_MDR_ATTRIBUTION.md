MDR SuperCon Datasheet Ver.240322 is published by the National Institute for
Materials Science (NIMS), https://doi.org/10.48505/nims.4487, under Creative
Commons Attribution 4.0 International (CC BY 4.0):
https://creativecommons.org/licenses/by/4.0/legalcode.

The packaged resource is a selected metadata projection of the oxide/metallic
table, `20240322_MDR_OAndM.txt`. It preserves complete original source-row hashes,
source IDs, physical line ranges and selected original numerical/bibliographic
cells. Organic rows and digitized figure assets are outside this projection.
The data do not establish scientific acceptance or the identity of a catalogue
sample or phase. Publication status was not independently checked.

Original table:
https://mdr.nims.go.jp/filesets/2347b413-9c15-43b7-90e6-41fe9243b1a5/download

Source SHA-256:
f599ef0040c18521e386f758ee826fe269f67ef369c1a007656035d03ccdfdf6

The versioned user guide, https://doi.org/10.48505/nims.4488, defines field
meanings and measurement-method codes. Absent units and undocumented codes
remain unresolved. Tc criteria are separate; `tcn` is a lower measurement
temperature from a non-superconducting report, and `pmax` is the maximum applied
pressure rather than the pressure of any Tc result.

Reproduce from the exact original public source bytes with:

    api/.venv/bin/python scripts/build_supercon_mdr_snapshot.py --source /path/to/20240322_MDR_OAndM.txt

The manifest records source/resource/decompressed hashes and projection bounds.
No publisher full text, coordinates or credentials are included.
