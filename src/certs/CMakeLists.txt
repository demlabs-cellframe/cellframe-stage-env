# Certificate Tools for Cellframe Node E2E Testing
# Minimal build - only crypto dependencies, no network stack
cmake_minimum_required(VERSION 3.10)
project(CellframeCertTools C)

# Allow overriding paths via command-line (for Docker builds)
if(NOT DEFINED CELLFRAME_SDK_BUILD)
    set(CELLFRAME_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk/build")
endif()

if(NOT DEFINED CELLFRAME_SDK_SRC)
    set(CELLFRAME_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk")
endif()

set(DAP_SDK_SRC "${CELLFRAME_SDK_SRC}/dap-sdk")

message(STATUS "Cellframe SDK Build: ${CELLFRAME_SDK_BUILD}")
message(STATUS "Cellframe SDK Source: ${CELLFRAME_SDK_SRC}")
message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")

# Detect target architecture
include(${DAP_SDK_SRC}/cmake/TargetArch_Detection.cmake)
target_architecture(TARGET_ARCH)

# Determine XKCP target based on architecture
if (${TARGET_ARCH} MATCHES "x86_64")
    set(XKCP_SUFFIX "x8664")
elseif(${TARGET_ARCH} MATCHES "armv7")
    set(XKCP_SUFFIX "armv7")
elseif(${TARGET_ARCH} MATCHES "armv8")
    set(XKCP_SUFFIX "armv8")
else()
    set(XKCP_SUFFIX "ref")
    message(WARNING "Unknown architecture ${TARGET_ARCH}, using reference XKCP implementation")
endif()

# Check for -march=native support
include(CheckCCompilerFlag)
CHECK_C_COMPILER_FLAG(-march=native COMPILER_SUPPORTS_MARCH_NATIVE)
if(COMPILER_SUPPORTS_MARCH_NATIVE)
    set(TARGET_POSTFIX "-native")
else()
    set(TARGET_POSTFIX "")
endif()

# Set XKCP paths
set(XKCP_TARGET "libdap-XKCP-${XKCP_SUFFIX}${TARGET_POSTFIX}.a")
set(XKCP_BUILD_DIR "${CELLFRAME_SDK_BUILD}/dap-sdk/crypto/XKCP/xkcp_build_src")
set(XKCP_BUILD_INCLUDES "${XKCP_BUILD_DIR}/bin/${XKCP_TARGET}.headers")

message(STATUS "Target architecture: ${TARGET_ARCH}")
message(STATUS "XKCP target: ${XKCP_TARGET}")

# Include directories - MINIMAL set for crypto only
include_directories(
    # Core
    ${DAP_SDK_SRC}/core/include
    ${DAP_SDK_SRC}/core/src
    ${DAP_SDK_SRC}/core/src/unix
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core
    
    # Crypto (full post-quantum support)
    ${DAP_SDK_SRC}/crypto/include
    ${DAP_SDK_SRC}/crypto/include/liboqs
    ${DAP_SDK_SRC}/crypto/include/oqs
    ${DAP_SDK_SRC}/crypto/include/sig_newhope
    ${DAP_SDK_SRC}/crypto/include/sig_sphincs
    ${DAP_SDK_SRC}/crypto/include/sig_dilithium
    ${DAP_SDK_SRC}/crypto/include/sig_falcon
    ${DAP_SDK_SRC}/crypto/include/seed
    ${XKCP_BUILD_INCLUDES}
    
    # 3rdparty
    ${DAP_SDK_SRC}/3rdparty/uthash/src
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core/json-c
    ${DAP_SDK_SRC}/3rdparty/json-c
    
    # I/O (for basic types)
    ${DAP_SDK_SRC}/io/include
    
    # Chain common (for dap_chain_addr_t)
    ${CELLFRAME_SDK_SRC}/modules/common/include
)

# Definitions
add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# Link directories - minimal
link_directories(
    ${CELLFRAME_SDK_BUILD}/dap-sdk/crypto
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core/json-c
    ${CELLFRAME_SDK_BUILD}/modules/common
    ${CELLFRAME_SDK_BUILD}/dap-sdk/io
)

# === cf-cert-generator ===
add_executable(cf-cert-generator cert-generator.c)

target_link_libraries(cf-cert-generator
    # Chain common (for address types)
    dap_chain_common
    # I/O
    dap_io
    # Crypto (full post-quantum)
    dap_crypto
    # Core
    dap_core
    dap_json-c
    # XKCP (hashing)
    ${XKCP_BUILD_DIR}/bin/${XKCP_TARGET}
    # Kyber (post-quantum KEM)
    ${CELLFRAME_SDK_BUILD}/dap-sdk/crypto/src/Kyber/crypto_kem/kyber512/optimized/libdap_crypto_kyber512.a
    # System
    pthread
    m
)

# === dap-cert (simple utility) ===
add_executable(dap-cert dap-cert.c)

target_link_libraries(dap-cert
    dap_chain_common
    dap_crypto
    dap_core
    dap_json-c
    ${XKCP_BUILD_DIR}/bin/${XKCP_TARGET}
    ${CELLFRAME_SDK_BUILD}/dap-sdk/crypto/src/Kyber/crypto_kem/kyber512/optimized/libdap_crypto_kyber512.a
    pthread
    m
)
