#!/bin/bash
set -e

DOCKER_USER="whatswithandyy"
IMAGE_NAME="swimcoach-api"
IMAGE_TAG="latest"
ENDPOINT_NAME="swimcoach-api"
CONTAINER_PORT=8000

: "${NEBIUS_API_KEY:?Set NEBIUS_API_KEY in your shell first (export NEBIUS_API_KEY=...)}"

TOKENFACTORY_BASE_URL="${TOKENFACTORY_BASE_URL:-https://api.tokenfactory.nebius.com/v1}"
MODEL_ID="${MODEL_ID:-meta-llama/Llama-3.3-70B-Instruct}"

FULL_IMAGE="docker.io/$DOCKER_USER/$IMAGE_NAME:$IMAGE_TAG"

echo "▶ Building Docker image..."
docker buildx build --platform linux/amd64 -t "$DOCKER_USER/$IMAGE_NAME:$IMAGE_TAG" --push 
echo "✓ Build complete"

echo "▶ Tagging as $FULL_IMAGE..."
docker tag "$IMAGE_NAME" "$FULL_IMAGE"

echo "▶ Pushing to Docker Hub..."
docker push "$FULL_IMAGE"
echo "✓ Image pushed"

echo "▶ Fetching subnet ID..."
SUBNET_ID=$(nebius vpc subnet list --format jsonpath='{.items[0].metadata.id}')
echo "  Subnet ID: $SUBNET_ID"

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
  --env "MODEL_ID=$MODEL_ID"

echo "✓ Endpoint creation requested"

echo ""
echo "▶ Waiting for endpoint to reach Running status..."
echo "  (This usually takes 2–3 minutes)"
echo ""

for i in $(seq 1 24); do
  STATE=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --format json \
    | jq -r '.status.state' 2>/dev/null || echo "UNKNOWN")
  echo "  [$i/24] State: $STATE"
  if [ "$STATE" = "RUNNING" ]; then
    break
  fi
  sleep 10
done

echo ""
ENDPOINT_IP=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" \
  --format json | jq -r '.status.public_endpoints[0]')

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Endpoint IP: $ENDPOINT_IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Test it:"
echo "  curl http://$ENDPOINT_IP/health"
echo ""
echo "Generate a plan:"
cat <<EOF
  curl -X POST http://$ENDPOINT_IP/generate-plan \\
    -H "Content-Type: application/json" \\
    -d '{
      "level": "intermediate",
      "goal": "endurance",
      "sessions_per_week": 3,
      "session_duration_minutes": 60,
      "pool_length": 25,
      "weeks": 4
    }'
EOF