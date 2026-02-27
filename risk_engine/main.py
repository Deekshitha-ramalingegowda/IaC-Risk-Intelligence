import json
from risk_engine.parsers.checkov_parser import parse_checkov
from risk_engine.scorer import RiskScorer
from risk_engine.governance import GovernanceEvaluator
import yaml


def main():

    # Load config
    with open("risk_engine/config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Parse Checkov output (temporary)
    findings = parse_checkov("checkov_output.json")

    # Score
    scorer = RiskScorer()
    total_score, domain_scores = scorer.calculate_score(findings)

    # Governance
    evaluator = GovernanceEvaluator(config)
    decision, reason = evaluator.evaluate(total_score, findings)

    # Final Output
    report = {
        "summary": {
            "total_score": total_score,
            "decision": decision,
            "reason": reason
        },
        "domain_scores": domain_scores
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()