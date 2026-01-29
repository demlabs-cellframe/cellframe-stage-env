#!/bin/bash
#
# Build Stage-Env Documentation PDFs
# Generates EN and RU versions of complete scenario language guide
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/_build"
EN_DIR="$SCRIPT_DIR/en"
RU_DIR="$SCRIPT_DIR/ru"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Stage-Env Documentation Builder ===${NC}"
echo ""

# Check dependencies
check_deps() {
    local missing=0
    
    if ! command -v pandoc &> /dev/null; then
        echo -e "${RED}✗ pandoc not found${NC}"
        echo "  Install: sudo apt-get install pandoc"
        missing=1
    else
        echo -e "${GREEN}✓ pandoc found${NC}"
    fi
    
    if ! command -v pdflatex &> /dev/null; then
        echo -e "${RED}✗ pdflatex not found${NC}"
        echo "  Install: sudo apt-get install texlive-latex-base texlive-fonts-recommended texlive-latex-extra"
        missing=1
    else
        echo -e "${GREEN}✓ pdflatex found${NC}"
    fi
    
    if [ $missing -eq 1 ]; then
        echo -e "${RED}Missing dependencies. Install them first.${NC}"
        exit 1
    fi
}

# Create build directory
prepare_build() {
    echo ""
    echo "Preparing build directory..."
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"
}

# Build English PDF
build_en() {
    echo ""
    echo -e "${YELLOW}Building English documentation...${NC}"
    
    local output="$BUILD_DIR/Stage-Env_Scenario_Language_Guide_EN.pdf"
    local temp_md="$BUILD_DIR/combined_en.md"
    
    # Combine all EN documents
    cat > "$temp_md" << 'EOF'
---
title: "Stage-Env Scenario Language - Complete Guide"
subtitle: "Declarative Testing for Blockchain Applications"
author: "Demlabs / Cellframe Team"
date: "2026-01-29"
version: "v2.1.0"
geometry: margin=2cm
documentclass: report
toc: true
toc-depth: 3
numbersections: true
colorlinks: true
linkcolor: blue
urlcolor: blue
---

\newpage

EOF
    
    # Add all scenario docs
    echo "# Part I: Scenario Language" >> "$temp_md"
    echo "" >> "$temp_md"
    
    if [ -f "$EN_DIR/scenarios/Tutorial.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/Tutorial.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/01_Language_Semantics.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/01_Language_Semantics.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/02_Language_Constructs.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/02_Language_Constructs.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/03_All_Operands.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/03_All_Operands.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/04_Test_Suites.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/04_Test_Suites.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/05_Debugging_Scenarios.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/05_Debugging_Scenarios.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/Cookbook.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/Cookbook.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    if [ -f "$EN_DIR/scenarios/Glossary.md" ]; then
        echo "\newpage" >> "$temp_md"
        cat "$EN_DIR/scenarios/Glossary.md" >> "$temp_md"
        echo "" >> "$temp_md"
    fi
    
    # Generate PDF
    pandoc "$temp_md" \
        -o "$output" \
        --pdf-engine=pdflatex \
        --highlight-style=tango \
        -V geometry:margin=2cm \
        -V fontsize=11pt \
        -V mainfont="DejaVu Sans" \
        -V monofont="DejaVu Sans Mono" \
        2>&1 || {
            echo -e "${RED}✗ Failed to generate EN PDF${NC}"
            return 1
        }
    
    echo -e "${GREEN}✓ English PDF created: $(basename $output)${NC}"
    echo "  Size: $(du -h "$output" | cut -f1)"
}

# Build Developer Guide
build_dev() {
    echo ""
    echo -e "${YELLOW}Building Developer Guide...${NC}"
    
    local output="$BUILD_DIR/Stage-Env_Developer_Guide_EN.pdf"
    local temp_md="$BUILD_DIR/dev_en.md"
    
    cat > "$temp_md" << 'EOF'
---
title: "Stage-Env Developer Guide"
subtitle: "Integration and Development"
author: "Demlabs / Cellframe Team"
date: "2026-01-29"
version: "v2.1.0"
geometry: margin=2cm
documentclass: report
toc: true
toc-depth: 2
numbersections: true
colorlinks: true
linkcolor: blue
urlcolor: blue
---

\newpage

EOF
    
    if [ -f "$EN_DIR/developer/DeveloperGuide.md" ]; then
        cat "$EN_DIR/developer/DeveloperGuide.md" >> "$temp_md"
    fi
    
    # Generate PDF
    pandoc "$temp_md" \
        -o "$output" \
        --pdf-engine=pdflatex \
        --highlight-style=tango \
        -V geometry:margin=2cm \
        -V fontsize=11pt \
        -V mainfont="DejaVu Sans" \
        -V monofont="DejaVu Sans Mono" \
        2>&1 || {
            echo -e "${RED}✗ Failed to generate Developer Guide PDF${NC}"
            return 1
        }
    
    echo -e "${GREEN}✓ Developer Guide PDF created: $(basename $output)${NC}"
    echo "  Size: $(du -h "$output" | cut -f1)"
}

# Main
main() {
    check_deps
    prepare_build
    build_en
    build_dev
    
    echo ""
    echo -e "${GREEN}=== Build Complete ===${NC}"
    echo ""
    echo "Generated PDFs:"
    ls -lh "$BUILD_DIR"/*.pdf | awk '{print "  " $9 " (" $5 ")"}'
    echo ""
    echo "Location: $BUILD_DIR/"
}

main "$@"
