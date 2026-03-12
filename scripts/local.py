#!/usr/bin/env python3

import os
import sys
import json
import subprocess
from pathlib import Path

from google import genai


MODEL = "models/gemini-2.5-flash"


# ===============================
# UTILITIES
# ===============================

def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set")
        sys.exit(1)
    return key


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
    return result.stdout


# ===============================
# RUN SECURITY SCAN
# ===============================

def run_checkov():

    print("Running Checkov...")

    cmd = [
        "checkov",
        "-d", ".",
        "--framework", "terraform",
        "-o", "json"
    ]

    output = run_cmd(cmd)

    with open("checkov-output.json", "w") as f:
        f.write(output)

    return json.loads(output)


# ===============================
# RUN COST SCAN
# ===============================

def run_infracost():

    print("Running Infracost...")

    cmd = [
        "infracost",
        "breakdown",
        "--path", ".",
        "--format", "json"
    ]

    output = run_cmd(cmd)

    with open("infracost-output.json", "w") as f:
        f.write(output)

    return json.loads(output)


# ===============================
# TERRAFORM PLAN
# ===============================

def load_terraform_plan():

    plan_file = "terraform-plan.txt"

    if not os.path.exists(plan_file):
        return "Terraform plan not provided."

    with open(plan_file, "r", encoding="utf8", errors="ignore") as f:
        return f.read()[:12000]


# ===============================
# PARSE CHECKOV
# ===============================

def parse_checkov(data):

    failed = data.get("results", {}).get("failed_checks", [])

    lines = []

    for c in failed[:100]:

        cid = c.get("check_id")
        resource = c.get("resource")
        name = c.get("check_name")

        lines.append(f"{cid} | {resource} | {name}")

    return "\n".join(lines)


# ===============================
# PARSE COST
# ===============================

def parse_cost(data):

    if not data:
        return "No cost data"

    resources = []

    for project in data.get("projects", []):

        for r in project.get("breakdown", {}).get("resources", []):

            name = r.get("name")
            rtype = r.get("resourceType")

            monthly = 0

            for c in r.get("costComponents", []):

                try:
                    monthly += float(c.get("monthlyCost", 0))
                except:
                    pass

            if monthly > 0:
                resources.append(
                    f"{name} ({rtype}) : ${monthly:.2f}/month"
                )

    return "\n".join(resources[:50])


# ===============================
# BUILD PROMPT
# ===============================

def build_prompt(plan, security, cost):

    return f"""
You are a senior cloud architect reviewing a Terraform pull request.

Inputs:
1. Terraform plan
2. Checkov security scan results
3. Infracost cost difference report

Your job is to analyze the infrastructure changes.

For each issue provide:

Finding
Risk
Cost Impact
Root Cause
Solution
Steps to Fix
Terraform Fix Example

Organize output under these sections:

Infrastructure Changes
Security Issues
Cost Impact
Reliability Concerns
Architecture Anti-Patterns

Example:

Security Issues

Finding:
Security group allows SSH from 0.0.0.0/0

Risk:
Anyone can attempt brute force login.

Cost Impact:
None

Root Cause:
Security group allows unrestricted inbound rule.

Solution:
Restrict SSH access to trusted CIDR.

Steps to Fix:
1. Identify trusted IP range
2. Update SG rule
3. Apply terraform

Terraform Fix Example:

resource "aws_security_group_rule" "ssh" {{
 type = "ingress"
 from_port = 22
 to_port = 22
 protocol = "tcp"
 cidr_blocks = ["10.0.0.0/24"]
}}

Terraform Plan:
{plan}

Checkov Results:
{security}

Infracost Diff:
{cost}
"""


# ===============================
# GEMINI CALL
# ===============================

def ask_gemini(prompt, api_key):

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 4000
        }
    )

    return response.text


# ===============================
# MAIN
# ===============================

def main():

    key = get_gemini_key()

    print("Running infrastructure analysis...")

    checkov_data = run_checkov()
    infracost_data = run_infracost()

    plan = load_terraform_plan()

    security = parse_checkov(checkov_data)
    cost = parse_cost(infracost_data)

    prompt = build_prompt(plan, security, cost)

    print("Running AI analysis...")

    result = ask_gemini(prompt, key)

    print("\n" + "="*80)
    print("AI INFRASTRUCTURE REVIEW")
    print("="*80)

    print(result)

    print("="*80)


if __name__ == "__main__":
    main()