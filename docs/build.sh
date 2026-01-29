#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define source and output directories
DOCS_DIR="$(dirname "$0")"
BUILD_DIR="${DOCS_DIR}/_build"
TEMP_DIR="${BUILD_DIR}/temp"

# Ensure directories exist
mkdir -p "${BUILD_DIR}" "${TEMP_DIR}"

# Function to remove emoji from files
remove_emoji() {
    local input_file="$1"
    local output_file="$2"
    # Remove emoji unicode characters (U+1F000 to U+1FFFF range and common symbols)
    # Keep: -, +, *, #, numbers, letters, spaces, punctuation
    perl -CSD -pe 's/[\x{1F000}-\x{1FFFF}\x{2700}-\x{27BF}\x{2B50}\x{2705}\x{274C}]//g' "$input_file" > "$output_file"
}

echo "Building documentation PDFs..."
echo ""
echo "Preparing emoji-free copies for PDF generation..."

# Prepare emoji-free versions of all markdown files
for lang in en ru; do
    for category in scenarios developer; do
        if [ -d "${DOCS_DIR}/${lang}/${category}" ]; then
            mkdir -p "${TEMP_DIR}/${lang}/${category}"
            for md_file in "${DOCS_DIR}/${lang}/${category}"/*.md; do
                if [ -f "$md_file" ]; then
                    filename=$(basename "$md_file")
                    remove_emoji "$md_file" "${TEMP_DIR}/${lang}/${category}/${filename}"
                fi
            done
        fi
    done
done

echo "✓ Emoji-free copies prepared"
echo ""

# --- English Scenario Language Guide ---
echo "Generating English Scenario Language Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_EN.pdf" \
  --pdf-engine=xelatex \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=11pt \
  --toc \
  --toc-depth=2 \
  --metadata title="Stage-Env Scenario Language Guide" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${TEMP_DIR}/en/scenarios/Tutorial.md" \
  "${TEMP_DIR}/en/scenarios/01_Language_Semantics.md" \
  "${TEMP_DIR}/en/scenarios/02_Language_Constructs.md" \
  "${TEMP_DIR}/en/scenarios/03_All_Operands.md" \
  "${TEMP_DIR}/en/scenarios/04_Test_Suites.md" \
  "${TEMP_DIR}/en/scenarios/05_Debugging_Scenarios.md" \
  "${TEMP_DIR}/en/scenarios/Cookbook.md" \
  "${TEMP_DIR}/en/scenarios/Glossary.md" 2>&1 | grep -v "Missing character" || true
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_EN.pdf"
echo ""

# --- English Developer Guide ---
echo "Generating English Developer Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Developer_Guide_EN.pdf" \
  --pdf-engine=xelatex \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=11pt \
  --toc \
  --toc-depth=2 \
  --metadata title="Stage-Env Developer Guide" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${TEMP_DIR}/en/developer/DeveloperGuide.md" 2>&1 | grep -v "Missing character" || true
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Developer_Guide_EN.pdf"
echo ""

# --- Russian Scenario Language Guide ---
echo "Generating Russian Scenario Language Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_RU.pdf" \
  --pdf-engine=xelatex \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=11pt \
  --toc \
  --toc-depth=2 \
  --metadata title="Stage-Env Руководство по Языку Сценариев" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${TEMP_DIR}/ru/scenarios/Tutorial.md" \
  "${TEMP_DIR}/ru/scenarios/01_Language_Semantics.md" \
  "${TEMP_DIR}/ru/scenarios/02_Language_Constructs.md" \
  "${TEMP_DIR}/ru/scenarios/03_All_Operands.md" \
  "${TEMP_DIR}/ru/scenarios/04_Test_Suites.md" \
  "${TEMP_DIR}/ru/scenarios/05_Debugging_Scenarios.md" \
  "${TEMP_DIR}/ru/scenarios/Cookbook.md" \
  "${TEMP_DIR}/ru/scenarios/Glossary.md" 2>&1 | grep -v "Missing character" || true
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Scenario_Language_Guide_RU.pdf"
echo ""

# --- Russian Developer Guide ---
echo "Generating Russian Developer Guide PDF..."
pandoc \
  --from markdown \
  --to pdf \
  --output "${BUILD_DIR}/Stage-Env_Developer_Guide_RU.pdf" \
  --pdf-engine=xelatex \
  --variable geometry:margin=1in \
  --variable mainfont="DejaVu Sans" \
  --variable monofont="DejaVu Sans Mono" \
  --variable fontsize=11pt \
  --toc \
  --toc-depth=2 \
  --metadata title="Stage-Env Руководство Разработчика" \
  --metadata author="Demlabs" \
  --metadata date="$(date +%Y-%m-%d)" \
  "${TEMP_DIR}/ru/developer/DeveloperGuide.md" 2>&1 | grep -v "Missing character" || true
echo "✓ Generated: ${BUILD_DIR}/Stage-Env_Developer_Guide_RU.pdf"
echo ""

# Cleanup temp files
rm -rf "${TEMP_DIR}"
echo "✓ Cleaned up temporary files"
echo ""

echo "================================================"
echo "Documentation build complete!"
echo "================================================"
echo ""
echo "Generated files:"
echo "  1. Stage-Env_Scenario_Language_Guide_EN.pdf"
echo "  2. Stage-Env_Developer_Guide_EN.pdf"
echo "  3. Stage-Env_Scenario_Language_Guide_RU.pdf"
echo "  4. Stage-Env_Developer_Guide_RU.pdf"
echo ""
echo "Output directory: ${BUILD_DIR}"
echo ""

# Show file sizes
if [ -d "${BUILD_DIR}" ]; then
  echo "File sizes:"
  ls -lh "${BUILD_DIR}"/*.pdf 2>/dev/null | awk '{print "  " $9 ": " $5}' || echo "  No PDF files found"
fi

echo ""
echo "Note: Emoji removed from PDFs (source markdown files unchanged)"
