#!/bin/sh
# Installs the test check before every push (.githooks/pre-push) on this computer, keeping Git LFS's own pre-push step.
# Run once from the project root: sh .githooks/install.sh
set -e
hooks=$(git rev-parse --git-common-dir)/hooks
mkdir -p "$hooks"
cat > "$hooks/pre-push" <<'HOOK'
#!/bin/sh
# simple-soccer: the tests (.githooks/pre-push of the checkout being pushed, if it has one), then Git LFS uploads the large files
input=$(cat)
if [ -f .githooks/pre-push ]; then
  printf '%s\n' "$input" | sh .githooks/pre-push "$@" || exit 1
fi
command -v git-lfs >/dev/null 2>&1 || { printf >&2 "\n%s\n\n" "This repository is configured for Git LFS but 'git-lfs' was not found on your path."; exit 2; }
printf '%s\n' "$input" | git lfs pre-push "$@"
HOOK
chmod +x "$hooks/pre-push"
echo "installed: $hooks/pre-push (tests before a push that changes code, then Git LFS)"
