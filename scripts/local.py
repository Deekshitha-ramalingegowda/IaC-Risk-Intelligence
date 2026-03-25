#!/usr/bin/env python3
"""
infrastructure-analysis.py
Reads checkov-output.json + infracost-output.json + Terraform sources,
calls Gemini, then writes:
  infrastructure-analysis-report.md
  infrastructure-analysis-report.json
  inline-comments.json
"""

import os, sys, json, re
from pathlib import Path
from datetime import datetime

try:
    from google import genai
except ImportError:
    print("google-genai not installed. Run: pip install google-genai")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-pro",
]

TERRAFORM_DIR = os.getenv("TERRAFORM_DIR", "terraform")

SEVERITY_MAP = {
    "CKV_AWS_126":  ("HIGH",   "🔴"),
    "CKV_AWS_8":    ("HIGH",   "🔴"),
    "CKV_AWS_135":  ("HIGH",   "🔴"),
    "CKV_AWS_25":   ("HIGH",   "🔴"),
    "CKV_AWS_260":  ("MEDIUM", "🟡"),
    "CKV_AWS_277":  ("MEDIUM", "🟡"),
    "CKV2_AWS_11":  ("HIGH",   "🔴"),
    "CKV2_AWS_12":  ("MEDIUM", "🟡"),
    "CKV2_AWS_41":  ("MEDIUM", "🟡"),
    "CKV_AWS_130":  ("LOW",    "🔵"),
}

# ─────────────────────────────────────────────────────────────────────────────
# FILE LOADING
# ─────────────────────────────────────────────────────────────────────────────

def load_json_file(filename):
    for enc in ["utf-8-sig", "utf-16", "utf-16-le", "utf-8", "latin-1"]:
        try:
            with open(filename, "r", encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    print(f"[ERROR] Could not parse {filename}")
    return None


def load_terraform_sources(terraform_dir=TERRAFORM_DIR):
    sources = {}
    for search_dir in [terraform_dir, "."]:
        base = Path(search_dir)
        if not base.is_dir():
            continue
        tf_files = sorted(base.rglob("*.tf"))
        if not tf_files:
            continue
        for tf_path in tf_files:
            try:
                rel = str(tf_path).lstrip("./\\")
                sources[rel] = tf_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"[WARN] Could not read {tf_path}: {e}")
        if sources:
            break
    return sources


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("[ERROR] GEMINI_API_KEY not set.")
        print("  Get: https://aistudio.google.com/app/apikey")
        print("  Then: export GEMINI_API_KEY=AIzaSy...")
        sys.exit(1)
    return key


# ─────────────────────────────────────────────────────────────────────────────
# DATA EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def extract_checkov_data(checkov_raw):
    results_list = checkov_raw if isinstance(checkov_raw, list) else [checkov_raw]
    all_failed, passed_count = [], 0
    for result in results_list:
        r = result.get("results", {})
        all_failed.extend(r.get("failed_checks", []))
        passed_count += len(r.get("passed_checks", []))
    return all_failed, passed_count


def format_checkov_for_prompt(failed, passed_count):
    if not failed:
        return f"✅ All {passed_count} checks passed."
    lines = [f"FAILED: {len(failed)}   PASSED: {passed_count}\n"]
    for check in failed:
        cid  = check.get("check_id", "N/A")
        name = check.get("check_name", "")
        res  = check.get("resource", "")
        fp   = check.get("file_path", "")
        lr   = check.get("file_line_range", [])
        sev, _ = SEVERITY_MAP.get(cid, ("MEDIUM", "🟡"))
        loc = fp + (f":{lr[0]}-{lr[1]}" if len(lr) == 2 else "")
        lines += [f"[{sev}] {cid} | {res} | {loc}", f"  Rule: {name}", ""]
    return "\n".join(lines)


def _safe_float(v):
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def extract_infracost_data(infracost_raw):
    total = _safe_float(infracost_raw.get("totalMonthlyCost"))
    hourly = _safe_float(infracost_raw.get("totalHourlyCost"))
    if total == 0 and hourly > 0:
        total = hourly * 730
    seen = {}
    for project in infracost_raw.get("projects", []):
        for key in ("breakdown", "diff"):
            for r in project.get(key, {}).get("resources", []):
                name = r.get("name", "unknown")
                rtype = r.get("resourceType", "")
                monthly = _safe_float(r.get("monthlyCost")) or _safe_float(r.get("hourlyCost")) * 730
                if name not in seen or monthly > seen[name][0]:
                    seen[name] = (monthly, name, rtype)
    return total, sorted(seen.values(), reverse=True)


def format_infracost_for_prompt(total, resource_costs):
    lines = [f"TOTAL MONTHLY: ${total:.2f}   ANNUAL: ${total * 12:.2f}\n"]
    for monthly, name, rtype in resource_costs[:15]:
        label = f"{name} ({rtype})" if rtype else name
        lines.append(f"  {label}: ${monthly:.2f}/mo" if monthly > 0 else f"  {label}: $0.00/mo (unpriced)")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI PROMPT
# ─────────────────────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are a senior cloud security and cost engineer reviewing a Terraform pull request.

Produce EXACTLY the two Markdown sections below — nothing before, nothing after.

## 🔐 Security Issues

For EVERY Checkov failed check, one table row:
| Severity | Check ID | Resource | File:Lines | Fix |
|----------|----------|----------|------------|-----|

After the table, for each HIGH/MEDIUM issue add:
### `CHECK_ID` – Title
**Why it matters:** One sentence.
**Fix:**
```hcl
<corrected snippet>
```

## 💰 Cost Impact

| Resource | Type/Config | Monthly | Annual | Recommendation |
|----------|-------------|---------|--------|----------------|

### Cost Summary
**Current total:** $X/mo
**Optimised total:** $X/mo
**Potential saving:** $X/mo

Rules:
- Reference exact file paths and line numbers from the source below.
- If a section has zero items, write: *(none)*

=============================================================
TERRAFORM SOURCE
=============================================================
{tf_sources}

=============================================================
CHECKOV FAILED CHECKS
=============================================================
{checkov_text}

=============================================================
INFRACOST BREAKDOWN
=============================================================
{infracost_text}
"""


def build_prompt(tf_sources, checkov_text, infracost_text):
    parts = []
    for rel_path, content in sorted(tf_sources.items()):
        numbered = "\n".join(f"{i+1:4d}  {l}" for i, l in enumerate(content.splitlines()))
        parts.append(f"\n### {rel_path}\n{numbered}")
    return ANALYSIS_PROMPT.format(
        tf_sources="\n".join(parts),
        checkov_text=checkov_text,
        infracost_text=infracost_text,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI CALL
# ─────────────────────────────────────────────────────────────────────────────

def ask_gemini(prompt, api_key):
    print("\n[INFO] Querying Gemini …")
    client = genai.Client(api_key=api_key)
    for model_name in MODELS:
        print(f"  Trying {model_name} … ", end="", flush=True)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"temperature": 0.1, "max_output_tokens": 3000},
            )
            text = (response.text or "").strip()
            if text:
                print("OK")
                return text
            print("empty response")
        except Exception as exc:
            print(f"failed — {str(exc)[:120]}")
    print("\n[ERROR] All Gemini models failed.")
    return "⚠️ Gemini analysis unavailable — check GEMINI_API_KEY and model quota."


# ─────────────────────────────────────────────────────────────────────────────
# INLINE COMMENT RULES
# (filename_exact, line_regex, severity, check_id, title, markdown_body)
# ─────────────────────────────────────────────────────────────────────────────

INLINE_RULES = [
    (
        "ec2.tf",
        r"monitoring\s*=\s*false",
        "🔴 HIGH", "CKV_AWS_126",
        "Detailed CloudWatch monitoring is disabled",
        "**Why it matters:** Metrics collected every 5 min instead of 1 min — hides short-lived CPU spikes.\n\n"
        "**Fix:**\n```hcl\nmonitoring = true\n```",
    ),
    (
        "ec2.tf",
        r'http_tokens\s*=\s*"optional"',
        "🔴 HIGH", "CKV_AWS_8",
        "IMDSv2 not enforced — metadata endpoint allows v1 requests",
        "**Why it matters:** IMDSv1 lets any process query IAM credentials without auth (SSRF risk).\n\n"
        "**Fix:**\n```hcl\nmetadata_options {\n  http_endpoint = \"enabled\"\n  http_tokens   = \"required\"\n}\n```",
    ),
    (
        "ec2.tf",
        r"encrypted\s*=\s*false",
        "🔴 HIGH", "CKV_AWS_135",
        "EBS volume is not encrypted at rest",
        "**Why it matters:** Unencrypted volumes expose data if a snapshot leaks or media is decommissioned.\n\n"
        "**Fix:**\n```hcl\nroot_block_device {\n  encrypted = true\n}\n```",
    ),
    (
        "ec2.tf",
        r'cidr_blocks\s*=\s*\["0\.0\.0\.0/0"\]',
        "🔴 HIGH", "CKV_AWS_25",
        "Security group allows unrestricted inbound access (0.0.0.0/0)",
        "**Why it matters:** SSH/HTTP open to the internet massively increases the attack surface.\n\n"
        "**Fix:**\n```hcl\ncidr_blocks = [\"10.0.0.0/8\"]  # restrict to known CIDR\n```",
    ),
    (
        "ec2.tf",
        r"instance_type\s*=\s*var\.ec2_instance_type",
        "💰 COST", "COST_EC2_OVERSIZE",
        "Default m5.2xlarge may be oversized (~$277/mo)",
        "**Why it matters:** m5.2xlarge costs ~$277/mo. m5.large (~$70) or t3.large (~$60) suits most workloads.\n\n"
        "**Fix in terraform.tfvars:**\n```hcl\nec2_instance_type = \"m5.large\"\n```",
    ),
    (
        "main.tf",
        r"enable_dns_hostnames\s*=\s*false",
        "🟡 MEDIUM", "CKV2_AWS_12",
        "VPC DNS hostnames are disabled",
        "**Why it matters:** Breaks SSM Session Manager, private hosted zones, ECS service discovery.\n\n"
        "**Fix:**\n```hcl\nenable_dns_hostnames = true\n```",
    ),
    (
        "main.tf",
        r"map_public_ip_on_launch\s*=\s*true",
        "🔵 LOW", "CKV_AWS_130",
        "Subnet auto-assigns public IPs on launch",
        "**Why it matters:** Instances get public IPs automatically, even when unintended.\n\n"
        "**Fix:**\n```hcl\nmap_public_ip_on_launch = false\n```",
    ),
]


def build_inline_comments(tf_sources):
    comments, seen = [], set()
    for rel_path, content in tf_sources.items():
        filename   = Path(rel_path).name
        file_lines = content.splitlines()
        for (target_file, line_regex, severity, check_id, title, detail) in INLINE_RULES:
            if filename != target_file:
                continue
            pattern = re.compile(line_regex, re.IGNORECASE)
            for lineno, raw_line in enumerate(file_lines, start=1):
                stripped = raw_line.strip()
                if stripped.startswith("#") or not pattern.search(stripped):
                    continue
                key = (rel_path, lineno, check_id)
                if key in seen:
                    continue
                seen.add(key)
                body = (
                    f"**[{severity}] `{check_id}` — {title}**\n\n"
                    f"📄 `{rel_path}` line {lineno}\n\n{detail}"
                )
                comments.append({"path": rel_path, "line": lineno, "body": body})
    return comments


# ─────────────────────────────────────────────────────────────────────────────
# REPORT HEADER
# ─────────────────────────────────────────────────────────────────────────────

def build_report_header(failed, passed_count, total_monthly):
    sev = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for check in failed:
        s, _ = SEVERITY_MAP.get(check.get("check_id", ""), ("MEDIUM", "🟡"))
        sev[s] = sev.get(s, 0) + 1
    return (
        "# 🏗️ Infrastructure Analysis Report\n\n"
        f"> Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        "## Summary\n\n"
        "| Metric | Value |\n|--------|-------|\n"
        f"| 🔴 High severity | {sev['HIGH']} |\n"
        f"| 🟡 Medium severity | {sev['MEDIUM']} |\n"
        f"| 🔵 Low severity | {sev['LOW']} |\n"
        f"| ✅ Checks passed | {passed_count} |\n"
        f"| 💰 Monthly cost estimate | ${total_monthly:.2f} |\n\n---\n\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────────────────────────────────────

def save_report(full_report, output_dir="."):
    md = f"{output_dir}/infrastructure-analysis-report.md"
    with open(md, "w", encoding="utf-8") as f:
        f.write(full_report)
        f.write(f"\n\n---\n*Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — Checkov + Infracost + Gemini*\n")
    print(f"  Saved: {md}")

    js = f"{output_dir}/infrastructure-analysis-report.json"
    with open(js, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "report": full_report}, f, indent=2)
    print(f"  Saved: {js}")


def save_inline_comments(comments, output_dir="."):
    path = f"{output_dir}/inline-comments.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(comments, f, indent=2)
    print(f"  Saved: {path}  ({len(comments)} comment(s))")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    api_key = get_gemini_key()

    for req in ["checkov-output.json", "infracost-output.json"]:
        if not os.path.exists(req):
            print(f"[ERROR] {req} not found. Run Checkov/Infracost first.")
            sys.exit(1)

    print("[INFO] Loading checkov-output.json …")
    checkov_raw = load_json_file("checkov-output.json")

    print("[INFO] Loading infracost-output.json …")
    infracost_raw = load_json_file("infracost-output.json")

    print(f"[INFO] Loading Terraform sources from '{TERRAFORM_DIR}/' …")
    tf_sources = load_terraform_sources()

    if not checkov_raw:
        print("[ERROR] Failed to parse checkov-output.json"); sys.exit(1)
    if not infracost_raw:
        print("[ERROR] Failed to parse infracost-output.json"); sys.exit(1)

    failed, passed_count   = extract_checkov_data(checkov_raw)
    total_monthly, rcosts  = extract_infracost_data(infracost_raw)
    checkov_text           = format_checkov_for_prompt(failed, passed_count)
    infracost_text         = format_infracost_for_prompt(total_monthly, rcosts)

    print(f"[INFO] Checkov — {len(failed)} failed, {passed_count} passed")
    print(f"[INFO] Infracost — ${total_monthly:.2f}/mo")
    print(f"[INFO] Terraform files — {len(tf_sources)}")

    gemini_body = ask_gemini(build_prompt(tf_sources, checkov_text, infracost_text), api_key)
    full_report = build_report_header(failed, passed_count, total_monthly) + gemini_body

    print("\n[INFO] Saving report …")
    save_report(full_report)

    print("[INFO] Building inline comments …")
    save_inline_comments(build_inline_comments(tf_sources))

    print("\n✅ Done.")
    print("  infrastructure-analysis-report.md   ← PR summary comment")
    print("  infrastructure-analysis-report.json ← CI artifact")
    print("  inline-comments.json                ← Files Changed tab pins")


if __name__ == "__main__":
    main()