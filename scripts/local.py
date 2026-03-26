import os
import json
import google.generativeai as genai

# ----------------------------
# CONFIG
# ----------------------------
TFSEC_FILE = "outputs/tfsec.json"
INFRACOST_FILE = "outputs/infracost.json"

# ----------------------------
# LOAD FILES
# ----------------------------
def load_json(file):
    if not os.path.exists(file):
        print(f"❌ Missing file: {file}")
        return None
    with open(file) as f:
        return json.load(f)

# ----------------------------
# EXTRACT DATA (TOKEN OPTIMIZED)
# ----------------------------
def extract_tfsec_issues(data):
    issues = []
    for r in data.get("results", [])[:10]:  # limit
        issues.append({
            "rule": r.get("rule_id"),
            "desc": r.get("description"),
            "severity": r.get("severity"),
            "resource": r.get("resource")
        })
    return issues

def extract_infracost(data):
    projects = data.get("projects", [])
    summary = []

    for p in projects:
        for r in p.get("breakdown", {}).get("resources", [])[:10]:
            summary.append({
                "name": r.get("name"),
                "monthly_cost": r.get("monthlyCost"),
                "type": r.get("resourceType")
            })

    return summary

# ----------------------------
# BUILD PROMPT (IMPORTANT 🔥)
# ----------------------------
def build_prompt(tfsec, infracost):
    return f"""
You are a Senior DevOps + FinOps + Cloud Security Engineer.

Analyze the infrastructure risks and cost issues.

### SECURITY FINDINGS
{json.dumps(tfsec, indent=2)}

### COST FINDINGS
{json.dumps(infracost, indent=2)}

---

Generate a structured report EXACTLY in this format:

Infrastructure Changes
- Finding:
- Risk:
- Cost Impact:
- Root Cause:
- Solution:
- Steps to Fix:
- Terraform Fix Example:

Security Issues
(same format)

Cost Impact
(same format)

Reliability Concerns
(same format)

---

Rules:
- Be concise but professional
- Prioritize critical issues first
- Suggest real Terraform fixes
- Avoid unnecessary explanation
"""

# ----------------------------
# CALL GEMINI
# ----------------------------
def call_ai(prompt):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise Exception("❌ GEMINI_API_KEY not set")

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel("gemini-1.5-flash")

    response = model.generate_content(prompt)

    return response.text

# ----------------------------
# SAVE REPORT
# ----------------------------
def save_report(text):
    with open("report.md", "w") as f:
        f.write(text)
    print("✅ Report saved: report.md")

# ----------------------------
# MAIN
# ----------------------------
def main():
    print("🚀 Starting AI Infra Analysis...")

    tfsec_data = load_json(TFSEC_FILE)
    infracost_data = load_json(INFRACOST_FILE)

    if not tfsec_data or not infracost_data:
        print("❌ Missing input data")
        return

    tfsec = extract_tfsec_issues(tfsec_data)
    cost = extract_infracost(infracost_data)

    prompt = build_prompt(tfsec, cost)

    print("📡 Calling AI...")
    result = call_ai(prompt)

    print("\n📊 OUTPUT:\n")
    print(result[:1500])  # preview

    save_report(result)

if __name__ == "__main__":
    main()