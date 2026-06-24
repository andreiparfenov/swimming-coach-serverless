#!/bin/bash
set -e

DOCKER_USER="whatswithandyy"
IMAGE_NAME="swimcoach-api"
IMAGE_TAG="latest"
ENDPOINT_NAME="swimcoach-api"
CONTAINER_PORT=8000

TOKENFACTORY_BASE_URL="https://api.tokenfactory.nebius.com/v1/"
MODEL_ID="meta-llama/Llama-3.3-70B-Instruct"
S3_BUCKET="${S3_BUCKET:-swim-program}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-https://storage.eu-north1.nebius.cloud}"

FULL_IMAGE="docker.io/$DOCKER_USER/$IMAGE_NAME:$IMAGE_TAG"

: "${NEBIUS_API_KEY:?Set NEBIUS_API_KEY in your shell first (export NEBIUS_API_KEY=...)}"
: "${S3_ACCESS_KEY:?Set S3_ACCESS_KEY in your shell first (export S3_ACCESS_KEY=...)}"
: "${S3_SECRET_KEY:?Set S3_SECRET_KEY in your shell first (export S3_SECRET_KEY=...)}"

echo "▶ Building and pushing image..."
docker buildx build --platform linux/amd64 -t "$FULL_IMAGE" --push .
echo "✓ Image pushed: $FULL_IMAGE"

echo "▶ Fetching subnet ID..."
SUBNET_ID=$(nebius vpc subnet list --format jsonpath='{.items[0].metadata.id}')
echo "  Subnet: $SUBNET_ID"

echo "▶ Creating Nebius endpoint..."
nebius ai endpoint create \
  --name "$ENDPOINT_NAME" \
  --image "$FULL_IMAGE" \
  --platform cpu-d3 \
  --preset 8vcpu-32gb \
  --public \
  --container-port "$CONTAINER_PORT" \
  --subnet-id "$SUBNET_ID" \
  --env "NEBIUS_API_KEY=$NEBIUS_API_KEY" \
  --env "TOKENFACTORY_BASE_URL=$TOKENFACTORY_BASE_URL" \
  --env "MODEL_ID=$MODEL_ID" \
  --env "S3_ACCESS_KEY=$S3_ACCESS_KEY" \
  --env "S3_SECRET_KEY=$S3_SECRET_KEY" \
  --env "S3_BUCKET=$S3_BUCKET" \
  --env "S3_ENDPOINT_URL=$S3_ENDPOINT_URL"

echo "✓ Endpoint creation requested"

echo ""
echo "▶ Waiting for Running status (2–3 min)..."

for i in $(seq 1 24); do
  STATE=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --format json \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',{}).get('state','UNKNOWN'))" 2>/dev/null \
    || echo "UNKNOWN")
  echo "  [$i/24] $STATE"
  [ "$STATE" = "RUNNING" ] && break
  sleep 10
done

ENDPOINT_IP=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --format json \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['status']['public_endpoints'][0])" 2>/dev/null || echo "check console")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Live at: http://$ENDPOINT_IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "curl http://$ENDPOINT_IP/health"