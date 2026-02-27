class GovernanceEvaluator:

    def __init__(self, config):
        self.config = config

    def evaluate(self, total_score, findings):

        # Hard Fail Rule: Critical Security
        for f in findings:
            if f.domain == "security" and f.severity == "critical":
                return "FAIL", "Critical security issue detected"

        thresholds = self.config["risk_thresholds"]

        if total_score >= thresholds["fail"]:
            return "FAIL", "Risk score exceeded fail threshold"

        elif total_score >= thresholds["review"]:
            return "REVIEW", "Risk score requires manual review"

        return "PASS", "Risk within acceptable limits"