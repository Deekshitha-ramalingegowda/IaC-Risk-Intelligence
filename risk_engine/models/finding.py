from dataclasses import dataclass
from typing import Optional, Dict


@dataclass
class Finding:
    id: str
    domain: str
    severity: str
    resource: str
    message: str
    tool_source: str
    multiplier: float = 1.0
    metadata: Optional[Dict] = None
