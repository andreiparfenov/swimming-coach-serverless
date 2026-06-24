#!/bin/bash
# deploy_job.sh — build, push, and run the SwimCoach data processing job
set -e

DOCKER_USER="${DOCKER_USER:-whatswithandyy}"   # override: export DOCKER_USER=<your-dockerhub-username>
JOB_IMAGE="swimcoach-job"
IMAGE_TAG="latest"
JOB_NAME="swimcoach-data-processor"
S3_BUCKET="${S3_BUCKET:-swim-program}"

FULL_IMAGE="docker.io/$DOCKER_USER/$JOB_IMAGE:$IMAGE_TAG"

# ---------------------------------------------------------------------------
# Env check
# ---------------------------------------------------------------------------
: "${NEBIUS_API_KEY:?export NEBIUS_API_KEY first}"
: "${S3_ACCESS_KEY:?export S3_ACCESS_KEY first}"
: "${S3_SECRET_KEY:?export S3_SECRET_KEY first}"

# ---------------------------------------------------------------------------
# Build and push job image
# ---------------------------------------------------------------------------
echo "▶ Building job image..."
docker buildx build \
  --platform linux/amd64 \
  -f Dockerfile.job \
  -t "$FULL_IMAGE" \
  --push .
echo "✓ Image pushed: $FULL_IMAGE"

# ---------------------------------------------------------------------------
# Ensure the target bucket exists and the job's service account can write
# to it. Idempotent: safe to re-run on every deploy.
#
# Nebius Object Storage denies access by default until a bucket-policy-rule
# explicitly grants a role to a subject (group or anonymous) — there is no
# implicit "owner of the project can always write" rule for static S3 keys.
# This block resolves the service account behind S3_ACCESS_KEY, puts it in
# a group, and grants that group storage.editor on the bucket.
# ---------------------------------------------------------------------------
echo "▶ Ensuring bucket '$S3_BUCKET' is writable by the job's service account..."

PARENT_ID="${NEBIUS_PARENT_ID:-$(python3 - <<'PYEOF'
import os, re
cfg_path = os.path.expanduser("~/.nebius/config.yaml")
with open(cfg_path) as f:
    content = f.read()
default_profile = re.search(r"^default:\s*(\S+)", content, re.M).group(1)
block = re.search(rf"^\s+{re.escape(default_profile)}:\n((?:\s+.+\n)+)", content, re.M).group(1)
print(re.search(r"parent-id:\s*(\S+)", block).group(1))
PYEOF
)}"

if ! nebius storage bucket get-by-name --name "$S3_BUCKET" >/dev/null 2>&1; then
  echo "  Bucket '$S3_BUCKET' not found — creating it..."
  nebius storage bucket create --name "$S3_BUCKET" --parent-id "$PARENT_ID" >/dev/null
else
  echo "  Bucket '$S3_BUCKET' already exists"
fi

BUCKET_ID=$(nebius storage bucket get-by-name --name "$S3_BUCKET" --format json \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['metadata']['id'])")

SA_ID=$(nebius iam v2 access-key list --parent-id "$PARENT_ID" --format json \
  | python3 -c "
import json, sys
keys = json.load(sys.stdin).get('items', [])
match = next((k for k in keys if k['status'].get('aws_access_key_id') == '$S3_ACCESS_KEY'), None)
print(match['spec']['account']['service_account']['id'] if match else '')
")

if [ -z "$SA_ID" ]; then
  echo "  ⚠ Could not resolve a service account for S3_ACCESS_KEY."
  echo "    Grant 'storage.editor' on bucket '$S3_BUCKET' to that key's owner manually, then re-run."
else
  GROUP_NAME="${S3_BUCKET}-writers"
  GROUP_ID=$(nebius iam group list --parent-id "$PARENT_ID" --format json \
    | python3 -c "
import json, sys
groups = json.load(sys.stdin).get('items', [])
match = next((g for g in groups if g['metadata']['name'] == '$GROUP_NAME'), None)
print(match['metadata']['id'] if match else '')
")

  if [ -z "$GROUP_ID" ]; then
    echo "  Creating IAM group '$GROUP_NAME'..."
    GROUP_ID=$(nebius iam group create --name "$GROUP_NAME" --parent-id "$PARENT_ID" --format json \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['metadata']['id'])")
  fi

  # Idempotent: ignore "already a member" errors on re-run
  nebius iam group-membership create --parent-id "$GROUP_ID" --member-id "$SA_ID" >/dev/null 2>&1 || true

  # NOTE: this REPLACES the bucket's policy rules wholesale. If you add other
  # rules later (e.g. for a second service account), include them all here.
  nebius storage bucket update --id "$BUCKET_ID" \
    --bucket-policy-rules "[{\"group_id\": \"$GROUP_ID\", \"paths\": [\"*\"], \"roles\": [\"storage.editor\"]}]" \
    >/dev/null
  echo "  ✓ Granted storage.editor on '$S3_BUCKET' to service account via group '$GROUP_NAME'"
fi

# ---------------------------------------------------------------------------
# Run Nebius Serverless Job
# ---------------------------------------------------------------------------
echo "▶ Submitting Nebius Serverless Job..."
nebius ai job create \
  --name "$JOB_NAME" \
  --image "$FULL_IMAGE" \
  --container-command "python3 process_training_data.py" \
  --platform cpu-d3 \
  --preset 4vcpu-16gb \
  --env "NEBIUS_API_KEY=$NEBIUS_API_KEY" \
  --env "S3_ACCESS_KEY=$S3_ACCESS_KEY" \
  --env "S3_SECRET_KEY=$S3_SECRET_KEY" \
  --env "S3_BUCKET=$S3_BUCKET" \
  --env "S3_ENDPOINT_URL=https://storage.eu-north1.nebius.cloud" \
  --env "MODEL_ID=meta-llama/Llama-3.3-70B-Instruct"

echo "Job submitted"
echo ""
echo "Stream logs:"
echo "  nebius ai job logs --follow \$(nebius ai job list --format json | python3 -c \"import json,sys; jobs=json.load(sys.stdin)['items']; print(next(j['metadata']['id'] for j in jobs if j['metadata']['name']=='$JOB_NAME'))\")"
