#!/bin/bash
# Push JRVS to GitHub
# Usage: ./push_to_github.sh [commit message]

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

MSG="${1:-chore: update JRVS}"

git add -A
git commit -m "$MSG"
git push origin main

echo "Done! Pushed to GitHub."
