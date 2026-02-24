#!/bin/bash

# ============================================================
# sync-upstream.sh
# Syncs local main branch with upstream origin/main
# ============================================================

set -e

BRANCH="main"
REMOTE="origin"

echo "🔄 Fetching latest from $REMOTE..."
git fetch $REMOTE

echo ""
echo "📊 Comparing local $BRANCH with $REMOTE/$BRANCH..."
BEHIND=$(git rev-list --count HEAD..$REMOTE/$BRANCH)
AHEAD=$(git rev-list --count $REMOTE/$BRANCH..HEAD)

echo "   ⬆  Ahead:  $AHEAD commit(s)"
echo "   ⬇  Behind: $BEHIND commit(s)"
echo ""

if [ "$BEHIND" -eq 0 ]; then
  echo "✅ Already up to date with $REMOTE/$BRANCH. Nothing to sync."
  exit 0
fi

echo "📝 Incoming changes from $REMOTE/$BRANCH:"
git log HEAD..$REMOTE/$BRANCH --oneline
echo ""

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
  echo "⚠️  You have uncommitted changes. Stashing them before pull..."
  git stash push -m "sync-upstream auto-stash $(date '+%Y-%m-%d %H:%M:%S')"
  STASHED=true
fi

echo "⬇️  Pulling changes from $REMOTE/$BRANCH..."
git pull $REMOTE $BRANCH

if [ "$STASHED" = true ]; then
  echo ""
  echo "📦 Restoring stashed changes..."
  git stash pop
fi

echo ""
echo "✅ Sync complete! Your $BRANCH is now up to date with $REMOTE/$BRANCH."
