"""Finite thermal-table profile; source declarations do not establish a state."""
from services.research_release_manifest import digest

PROFILE = "material-table-field/1.0.0"
FIELDS = {
    "electronic_specific_heat_coefficient_source_value": "reported_property",
    "debye_temperature_source_value": "reported_property",
}
REGISTRY_SHA256 = digest(FIELDS)
GRID_VERSION = "source-table-grid/1.0.0"
MAX_COLUMNS = 16
MAX_ROWS = 32
