# Certificate Tools for Cellframe Node E2E Testing
cmake_minimum_required(VERSION 3.10)
project(CellframeCertTools C)

# Find Cellframe SDK build directory
set(CELLFRAME_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk/build")
set(CELLFRAME_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk")
set(DAP_SDK_SRC "${CELLFRAME_SDK_SRC}/dap-sdk")

# Detect target architecture (same way as DAP SDK does)
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

# Check if compiler supports -march=native
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
message(STATUS "XKCP headers: ${XKCP_BUILD_INCLUDES}")

# Include directories
include_directories(
    ${DAP_SDK_SRC}/core/include
    ${DAP_SDK_SRC}/crypto/include
    ${DAP_SDK_SRC}/crypto/include/liboqs
    ${DAP_SDK_SRC}/crypto/include/oqs
    ${DAP_SDK_SRC}/crypto/include/sig_newhope
    ${DAP_SDK_SRC}/crypto/include/sig_sphincs
    ${DAP_SDK_SRC}/crypto/include/sig_dilithium
    ${DAP_SDK_SRC}/crypto/include/sig_falcon
    ${DAP_SDK_SRC}/crypto/include/seed
    ${XKCP_BUILD_INCLUDES}
    ${DAP_SDK_SRC}/3rdparty/uthash/src
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core/json-c
    ${DAP_SDK_SRC}/3rdparty/json-c
    ${CELLFRAME_SDK_SRC}/modules/common/include
)

# Link directories
link_directories(
    ${CELLFRAME_SDK_BUILD}/dap-sdk/crypto
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core
    ${CELLFRAME_SDK_BUILD}/dap-sdk/core/json-c
    ${CELLFRAME_SDK_BUILD}/modules/common
)

# Build cf-cert-generator - multi-node certificate batch generator
add_executable(cf-cert-generator cert-generator.c)

target_link_libraries(cf-cert-generator
    dap_chain_common
    dap_crypto
    dap_core
    dap_json-c
    ${XKCP_BUILD_DIR}/bin/${XKCP_TARGET}
    ${CELLFRAME_SDK_BUILD}/dap-sdk/crypto/src/Kyber/crypto_kem/kyber512/optimized/libdap_crypto_kyber512.a
    pthread
    m
)

# Build dap-cert - single certificate management utility
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