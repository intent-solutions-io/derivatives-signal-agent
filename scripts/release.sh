#!/bin/bash
#
# Derivatives Signal Agent - Release Script
# Creates deliverable packages for buyers
#
# Usage:
#   ./scripts/release.sh [version]
#   ./scripts/release.sh 1.0.0
#
# Outputs:
#   releases/derivatives-signal-agent-v{VERSION}.zip     - Source bundle
#   releases/derivatives-signal-agent-v{VERSION}.tar.gz  - Docker save image
#   releases/DELIVERY-CHECKLIST.md                       - What to send buyer
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get version
VERSION=${1:-$(cat VERSION 2>/dev/null || echo "1.0.0")}
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="$REPO_ROOT/releases"
DOCKER_IMAGE="derivatives-signal-agent:v$VERSION"

echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Derivatives Signal Agent - Release Builder${NC}"
echo -e "${GREEN}  Version: $VERSION${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

mkdir -p "$RELEASE_DIR"

# Step 1: Tests
echo -e "${YELLOW}[1/6] Running tests...${NC}"
cd "$REPO_ROOT"
if command -v pytest &> /dev/null; then
    pytest tests/ -v --tb=short || {
        echo -e "${RED}Tests failed! Aborting release.${NC}"
        exit 1
    }
else
    echo -e "${YELLOW}pytest not found, skipping tests${NC}"
fi

# Step 2: Update VERSION
echo -e "${YELLOW}[2/6] Updating VERSION file...${NC}"
echo "$VERSION" > "$REPO_ROOT/VERSION"

# Step 3: Source ZIP
echo -e "${YELLOW}[3/6] Creating source bundle...${NC}"
ZIP_FILE="$RELEASE_DIR/derivatives-signal-agent-v$VERSION.zip"

git archive --format=zip --prefix="derivatives-signal-agent-v$VERSION/" \
    -o "$ZIP_FILE" HEAD \
    -- . ':(exclude)scripts' ':(exclude)CLAUDE.md' ':(exclude).claude'

# Add config.yaml for convenience
cd "$REPO_ROOT"
mkdir -p /tmp/dsa-extras
cp config.example.yaml /tmp/dsa-extras/config.yaml
cd /tmp/dsa-extras
zip -u "$ZIP_FILE" config.yaml
rm -rf /tmp/dsa-extras

echo -e "${GREEN}  Created: $ZIP_FILE${NC}"
echo -e "${GREEN}  Size: $(du -h "$ZIP_FILE" | cut -f1)${NC}"

# Step 4: Docker build
echo -e "${YELLOW}[4/6] Building Docker image...${NC}"
cd "$REPO_ROOT"
docker build -t "$DOCKER_IMAGE" -t derivatives-signal-agent:latest .

# Step 5: Docker export
echo -e "${YELLOW}[5/6] Exporting Docker image...${NC}"
DOCKER_TAR="$RELEASE_DIR/derivatives-signal-agent-v$VERSION-docker.tar.gz"
docker save "$DOCKER_IMAGE" | gzip > "$DOCKER_TAR"
echo -e "${GREEN}  Created: $DOCKER_TAR${NC}"
echo -e "${GREEN}  Size: $(du -h "$DOCKER_TAR" | cut -f1)${NC}"

# Step 6: Delivery checklist
echo -e "${YELLOW}[6/6] Creating delivery checklist...${NC}"
cat > "$RELEASE_DIR/DELIVERY-CHECKLIST.md" << EOF
# Derivatives Signal Agent v$VERSION - Delivery Checklist

## Files to Deliver

- [ ] \`derivatives-signal-agent-v$VERSION.zip\` - Source bundle ($(du -h "$ZIP_FILE" | cut -f1))
- [ ] \`derivatives-signal-agent-v$VERSION-docker.tar.gz\` - Docker image ($(du -h "$DOCKER_TAR" | cut -f1))

## Buyer Requirements

- Bybit API key (free)
- Coinglass API key (\$29/month)
- Anthropic API key (pay-per-use)
- Slack incoming webhook URL

## Delivery Message Template

\`\`\`
Your Derivatives Signal Agent v$VERSION is ready!

QUICK START:
1. Unzip and copy config.yaml
2. Set environment variables (Bybit, Coinglass, Anthropic, Slack)
3. Run doctor to verify: python doctor.py --config config.yaml
4. Start the agent: python main.py --config config.yaml

DOCKER:
docker load < derivatives-signal-agent-v$VERSION-docker.tar.gz
docker run -v \$(pwd)/config.yaml:/app/config.yaml:ro \\
           -e BYBIT_API_KEY=... -e BYBIT_API_SECRET=... \\
           -e COINGLASS_API_KEY=... -e ANTHROPIC_API_KEY=... \\
           derivatives-signal-agent:v$VERSION

ACCEPTANCE:
Run doctor.py and confirm all 7 checks pass.
7-day defect warranty for reproducible bugs.

DISCLAIMER: This software is for informational purposes only.
Not financial advice. Trading derivatives carries substantial risk.
\`\`\`

## Post-Delivery

- [ ] Buyer confirmed doctor tests pass
- [ ] Payment received
- [ ] Added to customer list

---
Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
EOF

echo -e "${GREEN}  Created: $RELEASE_DIR/DELIVERY-CHECKLIST.md${NC}"

# Summary
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Release v$VERSION Complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Files created in $RELEASE_DIR/:"
ls -lh "$RELEASE_DIR/"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Review DELIVERY-CHECKLIST.md"
echo "  2. Upload to Gumroad/Whop"
echo "  3. Send delivery message to buyer"
echo ""
