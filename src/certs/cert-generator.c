/**
 * @file cert-generator.c
 * @brief DAP Certificate Generator for Cellframe Node E2E Testing
 * @details Generates real DAP certificates using DAP SDK crypto module
 * 
 * @author Cellframe Development Team
 * @date 2025-09-30
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <time.h>
#include <errno.h>
#include <stdint.h>
#include <stdarg.h>

/* DAP SDK includes */
#include "dap_common.h"
#include "dap_cert.h"
#include "dap_cert_file.h"
#include "dap_enc_key.h"
#include "dap_enc_base58.h"
#include "dap_sign.h"
#include "dap_hash.h"
#include "dap_chain_common.h"

/* === Constants === */
#define LOG_TAG "cf-cert-generator"

/* Debug flag for verbose logging */
static bool s_debug_more = false;

/* Buffer sizes following DAP SDK conventions */
#define MAX_NODE_NAME_LEN       32
#define MAX_CERT_NAME_LEN       128
/* Use DAP SDK constant for address string size */
#define MAX_VALIDATOR_ADDR_LEN  DAP_ENC_BASE58_ENCODE_SIZE(sizeof(dap_chain_addr_t))
#define MAX_PATH_LEN            512
#define MAX_TIMESTAMP_LEN       64
#define FILE_BUFFER_SIZE        4096

/* Node configuration constants */
#define BASE_IP_OFFSET          9
#define CHAIN_ID_HEX           "0x1234"
#define MAX_NODE_COUNT          100 /* Maximum supported nodes */

/* Address generation constants */
#define ADDR_COMPONENTS        4
#define ADDR_COMPONENT_BITS    16

/* File permissions */
#define DIR_PERMISSIONS        0755
#define FILE_PERMISSIONS       0644

/* Return codes */
#define RET_SUCCESS            0
#define RET_ERROR              -1

/* === Data Structures === */

/**
 * @struct node_cert_t
 * @brief Structure representing a node certificate
 */
typedef struct {
    char node_name[MAX_NODE_NAME_LEN];
    int node_id;
    char validator_addr[MAX_VALIDATOR_ADDR_LEN];
    char cert_path[MAX_PATH_LEN];
    dap_cert_t *cert;
} node_cert_t;

/* === Helper Functions === */

/**
 * @brief Safely copy string with size checking
 */
static int safe_strncpy(char *dest, size_t dest_size, const char *src) {
    if (!dest || !src || dest_size == 0) {
        log_it(L_ERROR, "Invalid parameters for safe_strncpy");
        return RET_ERROR;
    }
    
    size_t src_len = strlen(src);
    if (src_len >= dest_size) {
        log_it(L_ERROR, "String truncation would occur (len=%zu, max=%zu)", 
               src_len, dest_size - 1);
        return RET_ERROR;
    }
    
    strncpy(dest, src, dest_size - 1);
    dest[dest_size - 1] = '\0';
    return RET_SUCCESS;
}

/**
 * @brief Safely format string with size checking
 */
static int safe_snprintf(char *dest, size_t dest_size, const char *format, ...) {
    if (!dest || !format || dest_size == 0) {
        log_it(L_ERROR, "Invalid parameters for safe_snprintf");
        return RET_ERROR;
    }
    
    va_list args;
    va_start(args, format);
    int result = vsnprintf(dest, dest_size, format, args);
    va_end(args);
    
    if (result < 0 || (size_t)result >= dest_size) {
        log_it(L_ERROR, "snprintf truncation or error (result=%d, size=%zu)", 
               result, dest_size);
        return RET_ERROR;
    }
    
    return RET_SUCCESS;
}

/**
 * @brief Create directory with proper error handling
 */
static int create_directory(const char *path) {
    if (!path || strlen(path) == 0) {
        log_it(L_ERROR, "Invalid directory path");
        return RET_ERROR;
    }
    
    struct stat st = {0};
    
    if (stat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode)) {
            return RET_SUCCESS;
        } else {
            log_it(L_ERROR, "Path exists but is not a directory: %s", path);
            return RET_ERROR;
        }
    }
    
    if (mkdir(path, DIR_PERMISSIONS) != 0) {
        log_it(L_ERROR, "Failed to create directory %s: %s", path, strerror(errno));
        return RET_ERROR;
    }
    
    return RET_SUCCESS;
}

/**
 * @brief Generate validator address from certificate public key
 * Uses proper DAP SDK function for address generation
 * @param cert Certificate to generate address from
 * @param addr_out Output buffer for address string
 * @param addr_size Size of output buffer
 * @param network_id Network ID to use for address generation
 */
static int generate_validator_address(dap_cert_t *a_cert, char *a_addr_out, size_t a_addr_size, uint64_t a_network_id) {
    dap_return_val_if_pass(!a_cert || !a_cert->enc_key || !a_addr_out || a_addr_size < MAX_VALIDATOR_ADDR_LEN, RET_ERROR);
    
    debug_if(s_debug_more, L_DEBUG, "Generating validator address for cert=%p, network_id=0x%llX", 
             (void*)a_cert, (unsigned long long)a_network_id);
    
    /* Create address from certificate key using DAP SDK function */
    dap_chain_addr_t l_addr;
    memset(&l_addr, 0, sizeof(l_addr));
    
    /* Use provided network ID */
    dap_chain_net_id_t l_net_id = { .uint64 = a_network_id };
    
    int l_fill_result = dap_chain_addr_fill_from_key(&l_addr, a_cert->enc_key, l_net_id);
    if (l_fill_result != 0) {
        log_it(L_ERROR, "Failed to generate address from certificate key");
        return RET_ERROR;
    }
    
    debug_if(s_debug_more, L_DEBUG, "Address structure filled, converting to string");
    
    /* Convert address to string */
    const char *l_addr_str = dap_chain_addr_to_str(&l_addr);
    if (!l_addr_str) {
        log_it(L_ERROR, "Failed to convert address to string");
        return RET_ERROR;
    }
    
    /* Copy to output buffer with safety check */
    dap_return_val_if_pass(safe_strncpy(a_addr_out, a_addr_size, l_addr_str) != RET_SUCCESS, RET_ERROR);
    
    debug_if(s_debug_more, L_DEBUG, "Validator address generated successfully: %s", a_addr_out);
    return RET_SUCCESS;
}

/**
 * @brief Copy file safely
 */
static int copy_file(const char *src_path, const char *dst_path) {
    if (!src_path || !dst_path) {
        log_it(L_ERROR, "Invalid file paths for copy operation");
        return RET_ERROR;
    }
    
    FILE *src = fopen(src_path, "rb");
    dap_return_val_if_pass(!src, RET_ERROR);
    
    FILE *dst = fopen(dst_path, "wb");
    if (!dst) {
        fclose(src);
        log_it(L_ERROR, "Failed to open destination file %s", dst_path);
        return RET_ERROR;
    }
    
    char buffer[FILE_BUFFER_SIZE];
    size_t bytes_read;
    int result = RET_SUCCESS;
    
    while ((bytes_read = fread(buffer, 1, sizeof(buffer), src)) > 0) {
        size_t bytes_written = fwrite(buffer, 1, bytes_read, dst);
        if (bytes_written != bytes_read) {
            log_it(L_ERROR, "Write error during file copy");
            result = RET_ERROR;
            break;
        }
    }
    
    fclose(src);
    fclose(dst);
    
    if (result == RET_SUCCESS && chmod(dst_path, FILE_PERMISSIONS) != 0) {
        log_it(L_WARNING, "Failed to set permissions on %s", dst_path);
    }
    
    return result;
}

/**
 * @brief Save text to file
 */
static int save_to_file(const char *file_path, const char *content) {
    if (!file_path || !content) {
        log_it(L_ERROR, "Invalid parameters for save_to_file");
        return RET_ERROR;
    }
    
    FILE *fp = fopen(file_path, "w");
    dap_return_val_if_pass(!fp, RET_ERROR);
    
    fprintf(fp, "%s\n", content);
    fclose(fp);
    
    if (chmod(file_path, FILE_PERMISSIONS) != 0) {
        log_it(L_WARNING, "Failed to set permissions on %s", file_path);
    }
    
    return RET_SUCCESS;
}

/**
 * @brief Generate node certificate using DAP SDK crypto
 */
static int generate_node_certificate(node_cert_t *node, const char *output_dir, uint64_t network_id) {
    if (!node || !output_dir) {
        log_it(L_ERROR, "Invalid parameters for certificate generation");
        return RET_ERROR;
    }
    
    char node_dir[MAX_PATH_LEN];
    char cert_name[MAX_CERT_NAME_LEN];
    char cert_file_main[MAX_PATH_LEN];
    char cert_file_esbocs[MAX_PATH_LEN];
    char addr_file[MAX_PATH_LEN];
    
    /* Build paths */
    dap_return_val_if_pass(safe_snprintf(node_dir, sizeof(node_dir), 
                                          "%s/%s", output_dir, node->node_name) != RET_SUCCESS, 
                          RET_ERROR);
    
    dap_return_val_if_pass(safe_snprintf(cert_name, sizeof(cert_name), 
                                          "qevm-stagenet-node%d", node->node_id) != RET_SUCCESS, 
                          RET_ERROR);
    
    /* Create node directory */
    dap_return_val_if_pass(create_directory(node_dir) != RET_SUCCESS, RET_ERROR);
    
    /* Save node directory path */
    dap_return_val_if_pass(safe_strncpy(node->cert_path, sizeof(node->cert_path), 
                                         node_dir) != RET_SUCCESS, 
                          RET_ERROR);
    
    log_it(L_INFO, "Generating certificate for %s (node_id=%d)", node->node_name, node->node_id);
    debug_if(s_debug_more, L_DEBUG, "Calling dap_cert_generate_mem for %s", cert_name);
    
    /* Generate DAP certificate in memory with Dilithium signature */
    node->cert = dap_cert_generate_mem(cert_name, DAP_ENC_KEY_TYPE_SIG_DILITHIUM);
    if (!node->cert) {
        log_it(L_ERROR, "Failed to generate DAP certificate for %s", node->node_name);
        return RET_ERROR;
    }
    
    debug_if(s_debug_more, L_DEBUG, "Certificate generated in memory, saving to files");
    log_it(L_INFO, "Certificate generated successfully with Dilithium key");
    
    /* Generate validator address from certificate public key */
    if (generate_validator_address(node->cert, node->validator_addr, 
                                   sizeof(node->validator_addr), network_id) != RET_SUCCESS) {
        log_it(L_ERROR, "Failed to generate validator address");
        dap_cert_delete(node->cert);
        node->cert = NULL;
        return RET_ERROR;
    }
    
    debug_if(s_debug_more, L_DEBUG, "Validator address generated: %s", node->validator_addr);
    
    /* Save validator address */
    if (safe_snprintf(addr_file, sizeof(addr_file), 
                      "%s/validator_addr.txt", node_dir) == RET_SUCCESS) {
        save_to_file(addr_file, node->validator_addr);
    }
    
    if (safe_snprintf(addr_file, sizeof(addr_file), 
                      "%s/node_addr.txt", node_dir) == RET_SUCCESS) {
        save_to_file(addr_file, node->validator_addr);
    }
    
    /* Save certificate to files */
    if (safe_snprintf(cert_file_main, sizeof(cert_file_main), 
                      "%s/%s.dcert", node_dir, cert_name) != RET_SUCCESS) {
        dap_cert_delete(node->cert);
        node->cert = NULL;
        return RET_ERROR;
    }
    
    /* Save certificate to file using DAP SDK function */
    if (dap_cert_file_save(node->cert, cert_file_main) != 0) {
        log_it(L_ERROR, "Failed to save certificate to file: %s", cert_file_main);
        dap_cert_delete(node->cert);
        node->cert = NULL;
        return RET_ERROR;
    }
    
    debug_if(s_debug_more, L_DEBUG, "Certificate saved to %s", cert_file_main);
    log_it(L_INFO, "Certificate file saved: %s", cert_file_main);
    
    /* Create ESBocs consensus certificate (copy of main certificate) */
    if (safe_snprintf(cert_file_esbocs, sizeof(cert_file_esbocs), 
                      "%s/qevm.master.pvt.%d.dcert", node_dir, node->node_id - 1) == RET_SUCCESS) {
        if (copy_file(cert_file_main, cert_file_esbocs) == RET_SUCCESS) {
            log_it(L_INFO, "ESBocs certificate created: qevm.master.pvt.%d", node->node_id - 1);
        }
    }
    
    log_it(L_INFO, "Certificate generated for %s: %s", node->node_name, node->validator_addr);
    
    return RET_SUCCESS;
}

/**
 * @brief Generate PKI configuration JSON
 */
static int generate_pki_config(const node_cert_t *nodes, int node_count, const char *output_dir) {
    if (!nodes || !output_dir || node_count <= 0) {
        log_it(L_ERROR, "Invalid parameters for PKI config generation");
        return RET_ERROR;
    }
    
    char config_path[MAX_PATH_LEN];
    char timestamp[MAX_TIMESTAMP_LEN];
    time_t now;
    struct tm *tm_info;
    
    now = time(NULL);
    dap_return_val_if_pass(now == (time_t)-1, RET_ERROR);
    
    tm_info = gmtime(&now);
    dap_return_val_if_pass(!tm_info, RET_ERROR);
    
    dap_return_val_if_pass(strftime(timestamp, sizeof(timestamp), 
                                     "%Y-%m-%dT%H:%M:%SZ", tm_info) == 0, 
                          RET_ERROR);
    
    dap_return_val_if_pass(safe_snprintf(config_path, sizeof(config_path), 
                                          "%s/pki-config.json", output_dir) != RET_SUCCESS, 
                          RET_ERROR);
    
    FILE *fp = fopen(config_path, "w");
    dap_return_val_if_pass(!fp, RET_ERROR);
    
    /* Write JSON configuration */
    fprintf(fp, "{\n");
    fprintf(fp, "    \"network\": {\n");
    fprintf(fp, "        \"name\": \"qevm-stagenet\",\n");
    fprintf(fp, "        \"chain_id\": \"%s\",\n", CHAIN_ID_HEX);
    fprintf(fp, "        \"consensus\": \"esbocs\"\n");
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"nodes\": {\n");
    
    for (int i = 0; i < node_count; i++) {
        int cert_id = nodes[i].node_id - 1;
        int ip_last_octet = BASE_IP_OFFSET + nodes[i].node_id;
        
        fprintf(fp, "        \"%s\": {\n", nodes[i].node_name);
        fprintf(fp, "            \"id\": %d,\n", nodes[i].node_id);
        fprintf(fp, "            \"cert_id\": %d,\n", cert_id);
        fprintf(fp, "            \"dap_cert\": \"/certs/%s/qevm-stagenet-node%d.dcert\",\n",
                nodes[i].node_name, nodes[i].node_id);
        fprintf(fp, "            \"esbocs_cert\": \"/certs/%s/qevm.master.pvt.%d.dcert\",\n",
                nodes[i].node_name, cert_id);
        fprintf(fp, "            \"validator_addr\": \"%s\",\n", nodes[i].validator_addr);
        fprintf(fp, "            \"ip\": \"172.20.0.%d\"\n", ip_last_octet);
        fprintf(fp, "        }%s\n", (i < node_count - 1) ? "," : "");
    }
    
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"validators_addrs\": [");
    
    for (int i = 0; i < node_count; i++) {
        fprintf(fp, "\"%s\"%s", nodes[i].validator_addr, 
                (i < node_count - 1) ? ", " : "");
    }
    
    fprintf(fp, "],\n");
    fprintf(fp, "    \"generated\": \"%s\"\n", timestamp);
    fprintf(fp, "}\n");
    
    fclose(fp);
    
    if (chmod(config_path, FILE_PERMISSIONS) != 0) {
        log_it(L_WARNING, "Failed to set permissions on %s", config_path);
    }
    
    log_it(L_INFO, "PKI configuration generated: %s", config_path);
    
    return RET_SUCCESS;
}

/**
 * @brief Main entry point
 */
int main(int argc, char *argv[]) {
    const char *output_dir = "/certs";
    node_cert_t *nodes = NULL;
    int ret = RET_SUCCESS;
    uint64_t network_id = 0x1234;  /* Default stagenet network ID */
    int node_count = 0;
    
    /* Initialize DAP SDK FIRST - before ANY other DAP calls */
    dap_log_level_set(L_DEBUG);
    dap_enc_key_init();
    
    debug_if(s_debug_more, L_NOTICE, "=== Initializing DAP Certificate Generator ===");
    
    /* Parse command line arguments */
    if (argc < 3) {
        log_it(L_ERROR, "Usage: %s <output_directory> <node_count> [network_id_hex]", argv[0]);
        log_it(L_ERROR, "Example: %s /certs 6 0x1234  # 6 nodes", argv[0]);
        log_it(L_ERROR, "Example: %s /certs 3 0x1234  # 3 nodes", argv[0]);
        dap_enc_key_deinit();
        return RET_ERROR;
    }
    
    output_dir = argv[1];
    
    /* Parse node count */
    node_count = atoi(argv[2]);
    if (node_count <= 0 || node_count > MAX_NODE_COUNT) {
        log_it(L_ERROR, "Invalid node count: %d (must be 1-%d)", node_count, MAX_NODE_COUNT);
        dap_enc_key_deinit();
        return RET_ERROR;
    }
    
    /* Parse optional network ID argument */
    if (argc >= 4) {
        char *endptr;
        network_id = strtoull(argv[3], &endptr, 0);  /* 0 base allows 0x prefix */
        if (*endptr != '\0' || network_id == 0) {
            log_it(L_ERROR, "Invalid network ID format. Use hex format like 0x1234");
            dap_enc_key_deinit();
            return RET_ERROR;
        }
    }
    
    /* Allocate nodes array dynamically */
    nodes = DAP_NEW_Z_COUNT(node_cert_t, node_count);
    if (!nodes) {
        log_it(L_CRITICAL, "%s", c_error_memory_alloc);
        dap_enc_key_deinit();
        return RET_ERROR;
    }
    
    /* Validate output directory path */
    size_t path_len = strlen(output_dir);
    if (path_len == 0 || path_len >= MAX_PATH_LEN) {
        log_it(L_ERROR, "Invalid output directory path length");
        dap_enc_key_deinit();
        return RET_ERROR;
    }
    
    log_it(L_NOTICE, "=== DAP Certificate Generator for Cellframe Node E2E Testing ===");
    log_it(L_INFO, "Output directory: %s", output_dir);
    log_it(L_INFO, "Network ID: 0x%llX", (unsigned long long)network_id);
    log_it(L_INFO, "Node count: %d", node_count);
    log_it(L_INFO, "Signature type: Dilithium (post-quantum)");
    
    /* Create main output directory */
    if (create_directory(output_dir) != RET_SUCCESS) {
        DAP_DELETE(nodes);
        dap_enc_key_deinit();
        return RET_ERROR;
    }
    
    /* Initialize and generate certificates for each node */
    for (int i = 0; i < node_count; i++) {
        char node_name[MAX_NODE_NAME_LEN];
        snprintf(node_name, sizeof(node_name), "node%d", i + 1);
        
        log_it(L_INFO, "Processing node %d/%d: %s", i+1, node_count, node_name);
        
        if (safe_strncpy(nodes[i].node_name, sizeof(nodes[i].node_name), 
                        node_name) != RET_SUCCESS) {
            log_it(L_ERROR, "Failed to copy node name");
            ret = RET_ERROR;
            goto cleanup;
        }
        
        nodes[i].node_id = i + 1;
        
        log_it(L_INFO, "Generating certificate for %s...", nodes[i].node_name);
        if (generate_node_certificate(&nodes[i], output_dir, network_id) != RET_SUCCESS) {
            log_it(L_ERROR, "Failed to generate certificate for %s", nodes[i].node_name);
            ret = RET_ERROR;
            goto cleanup;
        }
        
        log_it(L_NOTICE, "Certificate generated successfully for %s", nodes[i].node_name);
    }
    
    /* Generate PKI configuration */
    if (generate_pki_config(nodes, node_count, output_dir) != RET_SUCCESS) {
        ret = RET_ERROR;
        goto cleanup;
    }
    
    if (ret == RET_SUCCESS) {
        log_it(L_NOTICE, "=== Certificate generation completed successfully ===");
        log_it(L_INFO, "Total certificates: %d", node_count);
    }
    
cleanup:
    /* Cleanup certificates */
    for (int i = 0; i < node_count; i++) {
        if (nodes[i].cert) {
            dap_cert_delete(nodes[i].cert);
            nodes[i].cert = NULL;
        }
    }
    
    /* Free nodes array */
    DAP_DELETE(nodes);
    
    /* Deinitialize DAP SDK encryption key subsystem */
    dap_enc_key_deinit();
    
    if (ret != RET_SUCCESS) {
        log_it(L_ERROR, "=== Certificate generation failed ===");
    }
    
    return ret;
}