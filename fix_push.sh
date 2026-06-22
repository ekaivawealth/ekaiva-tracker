#!/usr/bin/env bash
# Run this in Git Bash to remove deploy.sh from history and re-push cleanly
cd ~/index_sma_tracker

echo ""
echo ">>> Removing deploy.sh (it contains a secret — must not be in repo)..."
rm -f deploy.sh

echo ">>> Adding deploy.sh to .gitignore so it stays out of future commits..."
echo "deploy.sh" >> .gitignore

echo ">>> Erasing the previous commit (keeps all other files)..."
git update-ref -d HEAD

echo ">>> Re-staging everything (deploy.sh is now excluded)..."
git add -A
echo ""
echo "Files that will be committed:"
git status --short

echo ""
echo ">>> Committing..."
git commit -m "Initial deploy: SMA/EMA tracker with GitHub Actions"

echo ""
echo ">>> Pushing to GitHub..."
git push -u origin main --force

echo ""
echo "============================================"
echo " DONE! Your code is now live on GitHub."
echo " https://github.com/ekaivawealth/ekaiva-tracker"
echo "============================================"
echo ""
