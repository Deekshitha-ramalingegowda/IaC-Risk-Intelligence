import yaml
from collections import defaultdict


class RiskScorer:

    def __init__(self, config_path="risk_engine/config/config.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.severity_weights = self.config["severity_weights"]
        self.domain_weights = self.config["domain_weights"]

    def calculate_score(self, findings):

        domain_scores = defaultdict(float)

        for finding in findings:
            severity_weight = self.severity_weights.get(
                finding.severity.lower(), 1
            )

            score = severity_weight * finding.multiplier
            domain_scores[finding.domain] += score

        total_score = 0

        for domain, score in domain_scores.items():
            weight = self.domain_weights.get(domain, 0)
            total_score += score * weight

        return round(total_score, 2), domain_scores