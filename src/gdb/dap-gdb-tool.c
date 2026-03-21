/**
 * @file dap-gdb-tool.c
 * @brief DAP Global Database Management Tool
 * @details Standalone utility for direct GDB operations without running a node.
 *          Reads node configuration to locate the GDB backend, then performs
 *          low-level driver operations: list keys, read/write/delete records,
 *          and specialized node IP updates for snapshot re-hosting.
 *
 * Commands:
 *   list-keys    - List all keys in a GDB group
 *   read         - Read a record (hex dump)
 *   delete       - Delete a record
 *   node-rehost  - Update host/port in a nodes.list entry
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <arpa/inet.h>

#include "dap_common.h"
#include "dap_time.h"
#include "dap_global_db_driver.h"
#include "dap_global_db_pkt.h"

/* Inline node_info_t — avoids pulling in the heavy cellframe-sdk net stack */
typedef union {
    uint8_t  raw[8];
    uint64_t uint64;
} DAP_ALIGN_PACKED gdb_cell_id_t;

typedef struct {
    dap_stream_node_addr_t address;
    gdb_cell_id_t          cell_id;
    char                   alias[64];
    uint16_t               ext_port;
    uint8_t                ext_host_len;
    char                   ext_host[];
} DAP_ALIGN_PACKED gdb_node_info_t;

#define LOG_TAG "dap-gdb-tool"

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

static void s_print_usage(const char *a_prog)
{
    printf("DAP GlobalDB Management Tool\n\n");
    printf("Usage: %s --driver <name> --db-path <path> <command> [args]\n\n", a_prog);
    printf("Global options:\n");
    printf("  --driver <name>    GDB driver: mdbx, sqlite, pgsql\n");
    printf("  --db-path <path>   Path to global_db storage directory\n\n");
    printf("Commands:\n");
    printf("  list-keys <group>\n");
    printf("      List all keys in a GDB group\n\n");
    printf("  read <group> <key>\n");
    printf("      Read a record value (hex dump to stdout)\n\n");
    printf("  delete <group> <key>\n");
    printf("      Delete a record\n\n");
    printf("  node-rehost <net_name> <node_addr> <new_host> [new_port]\n");
    printf("      Update host (and optionally port) in a nodes.list entry.\n");
    printf("      <node_addr> is the short node address, e.g. 3FDA::0325::3A71::2C74\n");
    printf("      Reads existing entry, patches host/port, writes back.\n\n");
    printf("Examples:\n");
    printf("  %s --driver mdbx --db-path /opt/cellframe-node/var/lib/global_db \\\n", a_prog);
    printf("      list-keys vpntest.nodes.list\n\n");
    printf("  %s --driver mdbx --db-path /opt/cellframe-node/var/lib/global_db \\\n", a_prog);
    printf("      node-rehost vpntest 3FDA::0325::3A71::2C74 10.0.2.3 8079\n");
}

/* ------------------------------------------------------------------ */
/*  Command: list-keys                                                 */
/* ------------------------------------------------------------------ */

static int s_cmd_list_keys(const char *a_group)
{
    size_t l_count = 0;
    dap_store_obj_t *l_objs = dap_global_db_driver_read(a_group, NULL,
                                                        &l_count, true);
    if (!l_objs || !l_count) {
        fprintf(stderr, "No records found in group '%s'\n", a_group);
        return l_objs ? 0 : 1;
    }

    for (size_t i = 0; i < l_count; i++) {
        printf("%s\t%zu\n", l_objs[i].key ? l_objs[i].key : "(null)",
               l_objs[i].value_len);
    }
    dap_store_obj_free(l_objs, l_count);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: read                                                      */
/* ------------------------------------------------------------------ */

static int s_cmd_read(const char *a_group, const char *a_key)
{
    size_t l_count = 0;
    dap_store_obj_t *l_obj = dap_global_db_driver_read(a_group, a_key,
                                                       &l_count, true);
    if (!l_obj || !l_count) {
        fprintf(stderr, "Record '%s/%s' not found\n", a_group, a_key);
        return 1;
    }

    printf("group: %s\nkey: %s\nsize: %zu\ntimestamp: %llu\ncrc: 0x%016llx\n",
           l_obj->group, l_obj->key, l_obj->value_len,
           (unsigned long long)l_obj->timestamp,
           (unsigned long long)l_obj->crc);

    if (l_obj->value && l_obj->value_len) {
        printf("value (hex): ");
        for (size_t i = 0; i < l_obj->value_len; i++)
            printf("%02x", l_obj->value[i]);
        printf("\n");
    }

    dap_store_obj_free(l_obj, l_count);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: delete                                                    */
/* ------------------------------------------------------------------ */

static int s_cmd_delete(const char *a_group, const char *a_key)
{
    dap_store_obj_t l_obj = {
        .group     = (char *)a_group,
        .key       = (char *)a_key,
        .timestamp = dap_nanotime_now(),
    };
    int l_ret = dap_global_db_driver_delete(&l_obj, 1);
    if (l_ret) {
        fprintf(stderr, "Failed to delete '%s/%s', code %d\n",
                a_group, a_key, l_ret);
        return 1;
    }
    printf("OK\n");
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: node-rehost                                               */
/* ------------------------------------------------------------------ */

static int s_cmd_node_rehost(const char *a_net_name,
                             const char *a_node_addr_str,
                             const char *a_new_host,
                             const char *a_new_port_str)
{
    char l_group[256];
    snprintf(l_group, sizeof(l_group), "%s.nodes.list", a_net_name);

    /* Read existing record */
    size_t l_count = 0;
    dap_store_obj_t *l_obj = dap_global_db_driver_read(l_group,
                                                       a_node_addr_str,
                                                       &l_count, true);
    if (!l_obj || !l_count) {
        fprintf(stderr, "Record '%s/%s' not found\n", l_group, a_node_addr_str);
        return 1;
    }

    /* Validate existing value as gdb_node_info_t */
    if (l_obj->value_len < sizeof(gdb_node_info_t)) {
        fprintf(stderr, "Record too small (%zu < %zu), not a valid node_info\n",
                l_obj->value_len, sizeof(gdb_node_info_t));
        dap_store_obj_free(l_obj, l_count);
        return 1;
    }

    gdb_node_info_t *l_old_info = (gdb_node_info_t *)l_obj->value;

    /* Build new node_info with updated host */
    size_t l_new_host_len = strlen(a_new_host);
    size_t l_new_size = sizeof(gdb_node_info_t) + l_new_host_len + 1;
    gdb_node_info_t *l_new_info = calloc(1, l_new_size);
    if (!l_new_info) {
        dap_store_obj_free(l_obj, l_count);
        return 1;
    }

    l_new_info->address  = l_old_info->address;
    l_new_info->cell_id  = l_old_info->cell_id;
    memcpy(l_new_info->alias, l_old_info->alias, sizeof(l_new_info->alias));
    l_new_info->ext_port = a_new_port_str
        ? (uint16_t)atoi(a_new_port_str)
        : l_old_info->ext_port;
    l_new_info->ext_host_len = (uint8_t)l_new_host_len;
    memcpy(l_new_info->ext_host, a_new_host, l_new_host_len + 1);

    /* Prepare store object for writing */
    dap_store_obj_t l_new_obj = {
        .group     = l_group,
        .key       = (char *)a_node_addr_str,
        .value     = (byte_t *)l_new_info,
        .value_len = l_new_size,
        .timestamp = dap_nanotime_now(),
        .flags     = 0,
        .sign      = NULL,
        .crc       = 0,
    };

    /* Compute CRC (without sign — sign requires the node's private key) */
    l_new_obj.crc = dap_store_obj_checksum(&l_new_obj);

    int l_ret = dap_global_db_driver_add(&l_new_obj, 1);

    if (l_ret == 0) {
        printf("OK %s/%s -> %s:%s\n", l_group, a_node_addr_str,
               a_new_host,
               a_new_port_str ? a_new_port_str : "unchanged");
    } else {
        fprintf(stderr, "Failed to write '%s/%s', code %d\n",
                l_group, a_node_addr_str, l_ret);
    }

    free(l_new_info);
    dap_store_obj_free(l_obj, l_count);
    return l_ret ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/*  Main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv)
{
    if (argc < 4) {
        s_print_usage(argv[0]);
        return 1;
    }

    const char *l_driver  = NULL;
    const char *l_db_path = NULL;
    int l_cmd_start = 0;

    /* Parse global options */
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--driver") && i + 1 < argc) {
            l_driver = argv[++i];
        } else if (!strcmp(argv[i], "--db-path") && i + 1 < argc) {
            l_db_path = argv[++i];
        } else {
            l_cmd_start = i;
            break;
        }
    }

    if (!l_driver || !l_db_path || !l_cmd_start) {
        fprintf(stderr, "Error: --driver and --db-path are required\n\n");
        s_print_usage(argv[0]);
        return 1;
    }

    /* Minimal DAP SDK initialization — logging only, no event loop */
    dap_common_init("dap-gdb-tool", NULL);
    dap_log_level_set(L_WARNING);

    /* Initialize GDB driver */
    int l_rc = dap_global_db_driver_init(l_driver, l_db_path);
    if (l_rc) {
        fprintf(stderr, "Failed to initialize GDB driver '%s' at '%s', "
                "code %d\n", l_driver, l_db_path, l_rc);
        return 1;
    }

    const char *l_cmd = argv[l_cmd_start];
    int l_cmd_argc = argc - l_cmd_start - 1;
    char **l_cmd_argv = argv + l_cmd_start + 1;
    int l_ret = 1;

    if (!strcmp(l_cmd, "list-keys")) {
        if (l_cmd_argc < 1) {
            fprintf(stderr, "Usage: list-keys <group>\n");
        } else {
            l_ret = s_cmd_list_keys(l_cmd_argv[0]);
        }
    } else if (!strcmp(l_cmd, "read")) {
        if (l_cmd_argc < 2) {
            fprintf(stderr, "Usage: read <group> <key>\n");
        } else {
            l_ret = s_cmd_read(l_cmd_argv[0], l_cmd_argv[1]);
        }
    } else if (!strcmp(l_cmd, "delete")) {
        if (l_cmd_argc < 2) {
            fprintf(stderr, "Usage: delete <group> <key>\n");
        } else {
            l_ret = s_cmd_delete(l_cmd_argv[0], l_cmd_argv[1]);
        }
    } else if (!strcmp(l_cmd, "node-rehost")) {
        if (l_cmd_argc < 3) {
            fprintf(stderr, "Usage: node-rehost <net_name> <node_addr> "
                    "<new_host> [new_port]\n");
        } else {
            l_ret = s_cmd_node_rehost(l_cmd_argv[0], l_cmd_argv[1],
                                      l_cmd_argv[2],
                                      l_cmd_argc > 3 ? l_cmd_argv[3] : NULL);
        }
    } else {
        fprintf(stderr, "Unknown command: %s\n\n", l_cmd);
        s_print_usage(argv[0]);
    }

    dap_global_db_driver_deinit();
    return l_ret;
}
