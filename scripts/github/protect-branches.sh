#!/usr/bin/env bash
# Protects master (G-5). Needs an admin `gh` login; CI never runs this.
set -euo pipefail
repo="${1:-AmirrezaFarnamTaheri/Trade}"
gh api -X PUT "repos/${repo}/branches/master/protection" --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["rust (ubuntu-latest)", "rust (windows-latest)", "python", "Real-browser UI smoke (Edge, Windows)", "Secrets and dependency audit", "sbom", "rust-kernel"]},
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
JSON
echo "master is protected in ${repo}"
