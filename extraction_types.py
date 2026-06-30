from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class RuleExtractionResult:
    records: List[Dict[str, Any]] = field(default_factory=list)
    field_evidence: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
