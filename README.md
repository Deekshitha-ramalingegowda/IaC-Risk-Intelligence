# Infrastructure Analysis Tool

Automated security and cost analysis for Terraform infrastructure using Checkov, Infracost, and Google Gemini AI.

## Features

- **Security Analysis**: Deep security scanning using Checkov + Gemini AI
- **Cost Analysis**: Infrastructure cost optimization recommendations using Infracost + Gemini AI
- **Executive Summary**: Comprehensive PR merge decision recommendations
- **Token Optimized**: 98% reduction in API token usage compared to naive approaches

## Architecture

```
Terraform Code
    ↓
┌─────────────────────────┬──────────────────────────┐
│ Checkov (Security)      │ Infracost (Cost)         │
└────────────┬────────────┴────────────┬─────────────┘
             │                         │
      ┌──────▼──────────────────────────▼──────┐
      │  Optimized Summaries (5% of original)  │
      └──────┬──────────────────────────────────┘
             │
      ┌──────▼─────────────────────────┐
      │  Gemini API Analysis            │
      │  - Security findings            │
      │  - Cost optimizations           │
      │  - Executive summary            │
      └──────┬─────────────────────────┘
             │
      ┌──────▼─────────────────────────┐
      │  infrastructure-analysis-      │
      │  report.md / .json / .txt      │
      └─────────────────────────────────┘
```

## Prerequisites

### Local Setup

```bash
# Python 3.10+
python --version

# Install Checkov
pip install checkov

# Install Infracost
choco install infracost
# or download from https://www.infracost.io/docs/

# Get API Keys
# 1. Gemini API (free): https://aistudio.google.com/app/apikey
# 2. Infracost API (free): https://dashboard.infracost.io
```

### Environment Variables

```powershell
# PowerShell
$env:GEMINI_API_KEY = "AIzaSy..."
$env:INFRACOST_API_KEY = "your-key-here"

# Or set permanently (Windows)
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "AIzaSy...", "User")
[Environment]::SetEnvironmentVariable("INFRACOST_API_KEY", "your-key", "User")
```

## Installation

```bash
# Clone repository
git clone <repo-url>
cd IaC-Local

# Create virtual environment (recommended)
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows PowerShell

# Install dependencies
pip install -r scripts/requirements.txt
```

## Usage

### Local Execution

```bash
cd IaC-Local

# Run complete analysis
python scripts/local.py

# Output files generated:
# - infrastructure-analysis-report.md (Markdown for PR comments)
# - infrastructure-analysis-report.json (Full data for artifacts)
# - infrastructure-analysis-summary.txt (Brief summary)
```

### GitHub Actions Integration

Add to `.github/workflows/infrastructure-analysis.yml`:

```yaml
name: Infrastructure Analysis

on:
  pull_request:
    paths:
      - 'terraform/**'

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r scripts/requirements.txt
          sudo apt-get install -y checkov
          wget https://github.com/infracost/infracost/releases/download/v0.10.43/infracost-linux-x86_64.zip
          unzip infracost-linux-x86_64.zip
          sudo mv infracost /usr/local/bin/

      - name: Run infrastructure analysis
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          INFRACOST_API_KEY: ${{ secrets.INFRACOST_API_KEY }}
        run: python scripts/local.py

      - name: Comment on PR
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('infrastructure-analysis-report.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });
```

## Output

The tool generates three files:

### 1. infrastructure-analysis-report.md
Complete report with all analysis:
- Executive Summary (PR merge recommendation)
- Deep Security Analysis (threats, mitigations, roadmap)
- Cost Analysis (optimizations, savings estimates)

### 2. infrastructure-analysis-report.json
Machine-readable JSON format with all analysis data.

### 3. infrastructure-analysis-summary.txt
Brief text summary for email notifications.

## Example Output

```
INFRASTRUCTURE ANALYSIS REPORT

## Executive Summary

Overall Grade: C
Security Grade: D
Cost Efficiency Grade: B

PR Merge Decision: ⚠ APPROVE WITH CONDITIONS

Critical Issues:
- Open SSH access (port 22 to 0.0.0.0/0)
- Database with no encryption
- Oversized RDS instance ($815.80/month)

...
```

## Cost Optimization Example

For your test infrastructure ($1,295.26/month):

| Resource | Current | Recommended | Savings |
|----------|---------|-------------|---------|
| RDS DB | db.r5.2xlarge ($815.80) | db.r5.xlarge | $525.80/month |
| EC2 | m5.2xlarge ($330.32) | t3.large | $140/month |
| EBS Volumes | $80/month | Delete unused | $30/month |
| **Total** | **$1,295.26** | **Optimized** | **~$700/month savings** |

## Security Findings

Your test infrastructure has 60 security findings:
- 12 CRITICAL
- 18 HIGH
- 20 MEDIUM
- 10 LOW

Most common issues:
1. No encryption at rest (databases, volumes)
2. Open security groups to internet
3. No backup policies
4. Insufficient logging enabled

## Token Usage & Cost

| Metric | Before Optimization | After Optimization |
|--------|---------------------|-------------------|
| Checkov tokens | 79,859 | 1,407 |
| Infracost tokens | 11,381 | 830 |
| **Total tokens** | **91,240** | **2,237** |
| Cost per run | **$0.40** | **$0.0067** |
| Annual cost (25 runs/month) | **$120** | **$2.01** |
| **Savings** | — | **98% reduction** |

## Troubleshooting

### "GEMINI_API_KEY not set"
```powershell
$env:GEMINI_API_KEY = "your-key"
echo $env:GEMINI_API_KEY  # Verify
```

### "Checkov not found"
```bash
# Install in virtual environment
pip install checkov

# Verify
checkov --version
```

### Unicode encoding errors
```powershell
$env:PYTHONIOENCODING = 'utf-8'
python scripts/local.py
```

### API rate limiting (429 error)
- Check Gemini API quota: https://console.cloud.google.com/
- Wait 60 seconds before retrying
- Consider increasing rate limits for production use

## File Structure

```
IaC-Local/
├── scripts/
│   ├── local.py           # Main analysis script
│   ├── requirements.txt    # Python dependencies
│   └── __pycache__/        # (generated, ignored)
├── terraform/
│   └── main.tf            # Test infrastructure
├── .gitignore             # Git exclusions
├── README.md              # This file
└── (generated files ignored):
    ├── checkov-output.json
    ├── infracost-output.json
    └── infrastructure-analysis-report.*
```

## Dependencies

- Python 3.10+
- Checkov (security scanning)
- Infracost (cost analysis)
- google-genai (Gemini API client)

See `scripts/requirements.txt` for exact versions.

## License

[Add your license here]

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review Gemini API status: https://aistudio.google.com/
3. Verify Checkov/Infracost versions
4. Check GitHub Actions logs for workflow issues

## Next Steps

1. Set up GitHub Actions workflow (see section above)
2. Configure secrets in GitHub repository
3. Test on a non-critical PR first
4. Add to standard PR review process

## Notes for GitHub Actions

- Analysis runs on every PR that modifies `terraform/**` files
- Results posted automatically as PR comments
- Recommended to block merge on CRITICAL security issues
- Run manually to review cost before approving high-cost infrastructure
