#!/usr/bin/env python3
"""
infrastructure-analysis.py
Clean version: no summary, no noise, only real issues
"""

import os, sys, json, re
from pathlib import Path
from datetime import datetime

try:
    from google import genai
except ImportError:
    print("google-genai not installed. Run: pip install google-genai")
    sys.exit(1)

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-pro",
]

TERRAFORM_DIR = os.getenv("TERRAFORM_DIR", "terraform")

# Ignore low-value checks
IGNORE_CHECKS = {
    "CKV_AWS_130",
    "CKV_AWS_260",
    "CKV_AWS_277"
}

# ---------------------------------------------------------------------
# FILE LOADING
# ---------------------------------------------------------------------

def load_json_file(filename):
    for enc in ["utf-8-sig", "utf-16", "utf-8"]:
        try:
            with open(filename, "r", encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    return None


def load_terraform_sources(terraform_dir=TERRAFORM_DIR):
    sources = {}
    base = Path(terraform_dir)

    if base.is_dir():
        for tf in base.rglob("*.tf"):
            try:
                sources[str(tf)] = tf.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

    return sources


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("[ERROR] GEMINI_API_KEY not set")
        sys.exit(1)
    return key


# ---------------------------------------------------------------------
# CHECKOV
# ---------------------------------------------------------------------

def extract_checkov_data(checkov_raw):
    results = checkov_raw.get("results", {})

    failed = [
        c for c in results.get("failed_checks", [])
        if c.get("check_id") not in IGNORE_CHECKS
    ]

    passed = len(results.get("passed_checks", []))

    return failed, passed


def format_checkov_for_prompt(failed, passed):
    if not failed:
        return f"All {passed} checks passed."

    lines = [f"FAILED: {len(failed)} PASSED: {passed}\n"]

    for c in failed:
        cid = c.get("check_id")
        res = c.get("resource")
        path = c.get("file_path")
        lr = c.get("file_line_range", [])

        loc = f"{path}:{lr[0]}-{lr[1]}" if len(lr) == 2 else path
        lines.append(f"{cid} | {res} | {loc}")

    return "\n".join(lines)


# ---------------------------------------------------------------------
# INFRACOST
# ---------------------------------------------------------------------

def extract_infracost_data(data):
    total = float(data.get("totalMonthlyCost") or 0)
    return total, []


def format_infracost_for_prompt(total, _):
    return f"TOTAL MONTHLY COST: ${total:.2f}"


# ---------------------------------------------------------------------
# PROMPT (CLEAN)
# ---------------------------------------------------------------------

ANALYSIS_PROMPT = """
You are a senior DevOps and cloud security engineer reviewing Terraform code.

ONLY report REAL issues.

IGNORE:
- Missing descriptions
- Naming conventions
- Cosmetic issues

FOCUS ONLY ON:
- Security risks (open access, IMDS, encryption, IAM exposure)
- Cost issues (oversized instances, unnecessary resources)

--------------------------------------------------

Security Issue:

Finding:
Risk:
Root Cause:
Solution:

Steps to Fix:
1.
2.
3.

Terraform Fix:
```hcl
# corrected code
"""