"""Public display policy; original assertions and admission history are retained."""
from typing import Literal

from pydantic import BaseModel


class TcDisplayPolicy(BaseModel):
    version: Literal['tc-public-display/1'] = 'tc-public-display/1'
    maximum_kelvin: Literal[300] = 300
    exclusion_flag: Literal['tc_above_300k'] = 'tc_above_300k'
