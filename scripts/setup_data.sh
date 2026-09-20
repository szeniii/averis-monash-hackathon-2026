#!/usr/bin/env bash
#
# Copies the hackathon dataset into ./data/.
#
# The dataset is not committed to this repo, so every machine needs this once.
# Run from the repo root:
#
#     bash scripts/setup_data.sh                 # finds the bundle for you
#     bash scripts/setup_data.sh /path/to/bundle # or tell it where to look
#
set -euo pipefail

EXPECTED_EMAILS=520

# --- must be run from the repo root ---------------------------------------
if [ ! -d "sdoc" ]; then
    echo "✗ Run this from the repo root (the folder containing sdoc/)."
    echo "  You are in: $(pwd)"
    exit 1
fi

# --- is a folder actually the bundle? -------------------------------------
looks_like_bundle() {
    [ -d "$1/inbox" ] && [ -d "$1/attachments" ] && [ -f "$1/sample_submission.json" ]
}

# --- locate the bundle ----------------------------------------------------
BUNDLE="${1:-}"

if [ -n "$BUNDLE" ]; then
    BUNDLE="${BUNDLE%/}"                       # strip any trailing slash
    if ! looks_like_bundle "$BUNDLE"; then
        echo "✗ That folder doesn't look like the bundle: $BUNDLE"
        echo "  It should contain inbox/, attachments/ and sample_submission.json"
        exit 1
    fi
else
    echo "Looking for the dataset bundle..."
    for dir in "$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" "$HOME"; do
        [ -d "$dir" ] || continue
        while IFS= read -r candidate; do
            if looks_like_bundle "$candidate"; then
                BUNDLE="$candidate"
                break 2
            fi
        done < <(find "$dir" -maxdepth 3 -type d -name "*sdoc*" 2>/dev/null)
    done

    if [ -z "$BUNDLE" ]; then
        echo "✗ Couldn't find the bundle automatically."
        echo
        echo "  Pass its location instead — drag the folder from Finder into"
        echo "  your terminal after typing this, then press Enter:"
        echo
        echo "      bash scripts/setup_data.sh "
        exit 1
    fi
    echo "  Found: $BUNDLE"
fi

# --- copy -----------------------------------------------------------------
# --- refuse to silently use the organizers' package -----------------------
# data_v2/ in the organizers' Docker distribution has the same shape as the
# participant bundle, but also ships ground_truth.json. Same inbox, so the
# copy itself is harmless — but you should know which one you are on.
if [ -f "$BUNDLE/ground_truth.json" ]; then
    echo
    echo "⚠  This folder contains ground_truth.json — it is the ORGANIZERS'"
    echo "   package, not the participant bundle."
    echo "   $BUNDLE"
    echo
    echo "   The answer key will NOT be copied into data/, and it must not be"
    echo "   used to tune results — that risks disqualification. Use it only"
    echo "   via the scoring server's /submit endpoint."
    echo
    printf "   Continue with this folder? [y/N] "
    read -r reply
    case "$reply" in
        [yY]*) echo "   Continuing." ;;
        *) echo "   Aborted."; exit 1 ;;
    esac
fi

echo "Copying dataset into ./data/ ..."
# The trailing /. copies the folder *contents*, so re-running this script
# refreshes data/ instead of nesting data/inbox/inbox.
mkdir -p data/inbox data/attachments
cp -R "$BUNDLE/inbox/." data/inbox/
cp -R "$BUNDLE/attachments/." data/attachments/
cp "$BUNDLE/sample_submission.json" data/

# --- verify ---------------------------------------------------------------
emails=$(find data/inbox -name "email_*.json" | wc -l | tr -d ' ')
attachments=$(find data/attachments -type f ! -name ".*" | wc -l | tr -d ' ')

echo
if [ "$emails" -eq "$EXPECTED_EMAILS" ]; then
    echo "✓ Dataset ready — $emails emails, $attachments attachments."
else
    echo "⚠ Copied $emails emails (expected $EXPECTED_EMAILS) and $attachments attachments."
    echo "  Check that the bundle extracted completely."
    exit 1
fi
