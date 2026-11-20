#!/usr/bin/env bash
# Deploy the static demo to the Hugging Face Space builditwithgk/whittle-mcp (free tier).
# Needs: `hf auth login` done once. Run from the repo root:  bash space/deploy.sh
set -euo pipefail
SPACE="${SPACE:-builditwithgk/whittle-mcp}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
bash space/build.sh "$STAGE"
hf repos create "$SPACE" --repo-type space --space-sdk static --exist-ok
hf upload "$SPACE" "$STAGE" . --repo-type space --commit-message "Deploy from $(git rev-parse --short HEAD)"
echo "Deployed: https://huggingface.co/spaces/$SPACE"
