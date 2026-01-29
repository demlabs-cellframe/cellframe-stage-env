#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define source and output directories
DOCS_DIR="$(dirname "$0")"
BUILD_DIR="${DOCS_DIR}/_build"

# Ensure build directory exists
mkdir -p "${BUILD_DIR}"

echo "Building documentation PDFs..."

# --- English Scenario Language Guide ---
echo "Generating English Scenario Language Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_EN.pdf" \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=12pt \
  --toc \
  --toc-depth=3 \
  --metadata title="Stage-Env Scenario Language Guide" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${DOCS_DIR}/en/scenarios/Tutorial.md" \
  "${DOCS_DIR}/en/scenarios/01_Language_Semantics.md" \
  "${DOCS_DIR}/en/scenarios/02_Language_Constructs.md" \
  "${DOCS_DIR}/en/scenarios/03_All_Operands.md" \
  "${DOCS_DIR}/en/scenarios/04_Test_Suites.md" \
  "${DOCS_DIR}/en/scenarios/05_Debugging_Scenarios.md" \
  "${DOCS_DIR}/en/scenarios/Cookbook.md" \
  "${DOCS_DIR}/en/scenarios/Glossary.md"
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_EN.pdf"

# --- English Developer Guide ---
echo "Generating English Developer Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Developer_Guide_EN.pdf" \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=12pt \
  --toc \
  --toc-depth=3 \
  --metadata title="Stage-Env Developer Guide" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${DOCS_DIR}/en/developer/DeveloperGuide.md"
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Developer_Guide_EN.pdf"

# --- Russian Scenario Language Guide ---
echo "Generating Russian Scenario Language Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_RU.pdf" \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=12pt \
  --pdf-engine=xelatex \
  --toc \
  --toc-depth=3 \
  --metadata title="Stage-Env Руководство по Языку Сценариев" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${DOCS_DIR}/ru/scenarios/Tutorial.md" \
  "${DOCS_DIR}/ru/scenarios/01_Language_Semantics.md" \
  "${DOCS_DIR}/ru/scenarios/02_Language_Constructs.md" \
  "${DOCS_DIR}/ru/scenarios/03_All_Operands.md" \
  "${DOCS_DIR}/ru/scenarios/04_Test_Suites.md" \
  "${DOCS_DIR}/ru/scenarios/05_Debugging_Scenarios.md" \
  "${DOCS_DIR}/ru/scenarios/Cookbook.md" \
  "${DOCS_DIR}/ru/scenarios/Glossary.md"
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_RU.pdf"

# --- Russian Developer Guide ---
echo "Generating Russian Developer Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Developer_Guide_RU.pdf" \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=12pt \
  --pdf-engine=xelatex \
  --toc \
  --toc-depth=3 \
  --metadata title="Stage-Env Руководство Разработчика" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${DOCS_DIR}/ru/developer/DeveloperGuide.md"
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Developer_Guide_RU.pdf"

echo ""
echo "Documentation build complete!"
echo ""
echo "Generated files:"
echo "  - Stage-Env_Scenario_Language_Guide_EN.pdf"
echo "  - Stage-Env_Developer_Guide_EN.pdf"
echo "  - Stage-Env_Scenario_Language_Guide_RU.pdf"
echo "  - Stage-Env_Developer_Guide_RU.pdf"
echo ""
echo "Output directory: ${BUILD_DIR}"
