"""Search-taxonomy regression examples; not a measured scientific accuracy set."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from services.materials_family import FAMILIES, classify_material_family, current_family


@pytest.mark.parametrize('formula,family', [
    (r'\mathrm{Bi_{2-x}Pb_xSr_2CaCu_2O_{8+ \delta }}', 'cuprate'),
    ('YBCO6.8','cuprate'), ('YbCo','intermetallic'),
    ('Nd1.85Ce0.15CuO4','cuprate'), ('LaFeAsO1-xFx','iron_based'),
    ('Ba(Fe1-xCox)2As2','iron_based'), ('FeSe','iron_based'),
    ('Lix(C2H8N2)yFe2-zSe2','iron_based'), ('CaFe1-xCoxAsH','iron_based'),
    ('Nd0.8Sr0.2NiO2','nickelate'), ('LaNiPO','oxide'), ('LaONiAs','oxide'),
    ('CeRu2','intermetallic'), ('CeH9','hydride'), ('CeCoIn5','heavy_fermion'),
    ('UTe2','heavy_fermion'), ('U6Co','intermetallic'), ('CsV3Sb5','kagome'),
    ('CsV2Sb3','intermetallic'), ('K2Cr3As3','pnictide'),
    ('Sr2RuO4','ruthenate'), ('LaO1-xFxBiS2','bis2_layered'),
    ('Bi2Se3','chalcogenide'), ('YNi2B2C','borocarbide'),
    ('Ba0.6K0.4BiO3','bismuthate'), ('H3S','hydride'),
    ('NbN','nitride'), ('MgB2','mgb2'), ('Mg(B1-xCx)2','mgb2'),
    ('MgB4','boride'), ('Mo2C','carbide'), ('CaC6','carbon'),
    ('K3C60','fulleride'), ('(NH3)0.75NaK2C60','fulleride'),
    (r'$\kappa$-(BEDT-TTF)$_2$Cu(NCS)$_2$', 'organic'),
    ('Nb','elemental'), ('V','elemental'), ('Ti/Nb/Al','heterostructure'),
    ('FeSe/SrTiO3','heterostructure'), ('Nb-Ti','intermetallic'),
    (r'\pccox{1.85}{0.15}\xspace','unclassified'),
    ('Fe2??Se','unclassified'), ('Bi2Sr1.6L0.4CuO6+δ','unclassified'),
    ('Li5/6BC','unclassified'), ('not a material','unclassified'),
    (r'ErNi2\,^{11}B2C','unclassified'), ('FeSe(10nm)/STO','unclassified'),
])
def test_family_boundaries(formula,family):
    assert classify_material_family(formula)['family'] == family


def test_original_notation_variables_and_stale_labels_are_not_overwritten():
    formula=r'\mathrm{Bi_{2-x}Pb_xSr_2CaCu_2O_{8+\delta}}'
    result=classify_material_family(formula)
    assert result['formula_status']=='variable'
    semantics=dict(family_classification=result)
    assert current_family(formula,'cuprate',semantics)=='cuprate'
    assert current_family('NbN','cuprate',semantics)=='unclassified'
    assert current_family(formula,'heavy_fermion',semantics)=='unclassified'
    stale=deepcopy(semantics);stale['family_classification']['version']='old'
    assert current_family(formula,'cuprate',stale)=='unclassified'


def test_ui_options_match_controlled_backend_vocabulary():
    text=(Path(__file__).parents[2]/'frontend/lib/material-families.ts').read_text()
    assert json.loads(text.split(' = ',1)[1].rstrip(';\n'))==FAMILIES
