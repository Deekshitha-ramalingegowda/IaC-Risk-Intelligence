import json
from risk_engine.models.finding import Finding


def parse_checkov(file_path: str):
    findings = []

    with open(file_path, "r") as f:
        data = json.load(f)

    for result in data.get("results", {}).get("failed_checks", []):
        finding = Finding(
            id=result.get("check_id"),
            domain="security",
            severity=result.get("severity", "medium").lower(),
            resource=result.get("resource"),
            message=result.get("check_name"),
            tool_source="checkov",
            multiplier=1.0,
            metadata=result
        )
        findings.append(finding)

    return findings
