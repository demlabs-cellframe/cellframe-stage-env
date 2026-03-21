/**
 * @file dap-gdb-tool.c
 * @brief DAP Global Database Management Tool
 * @details Standalone utility for direct GDB B-tree operations without running
 *          a node.  Uses the lightweight dap_global_db_groups_init() API.
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
#include "dap_global_db.h"
#include "dap_global_db_pkt.h"
#include "dap_global_db_btree.h"
#include "dap_cluster_node.h"

typedef union {
    uint8_t  raw[8];
    uint64_t uint64;
} DAP_ALIGN_PACKED gdb_cell_id_t;

typedef struct {
    dap_cluster_node_addr_t address;
    gdb_cell_id_t           cell_id;
    char                    alias[64];
    uint16_t                ext_port;
    uint8_t                 ext_host_len;
    char                    ext_host[];
} DAP_ALIGN_PACKED gdb_node_info_t;

#define LOG_TAG "dap-gdb-tool"

static void s_print_usage(const char *a_prog)
{
    printf("DAP GlobalDB Management Tool (B-tree native)\n\n");
    printf("Usage: %s --db-path <path> <command> [args]\n\n", a_prog);
    printf("Global options:\n");
    printf("  --db-path <path>   Path to global_db storage directory\n\n");
    printf("Commands:\n");
    printf("  list-keys <group>\n");
    printf("  read <group> <key>\n");
    printf("  delete <group> <key>\n");
    printf("  node-rehost <net_name> <node_addr> <new_host> [new_port]\n\n");
    printf("Examples:\n");
    printf("  %s --db-path /opt/cellframe-node/var/lib/global_db \\\n", a_prog);
    printf("      node-rehost vpntest 3FDA::0325::3A71::2C74 10.0.2.3 8079\n");
}

/* ------------------------------------------------------------------ */
/*  Command: list-keys                                                 */
/* ------------------------------------------------------------------ */

static int s_cmd_list_keys(const char *a_group)
{
    dap_global_db_t *l_tree = dap_global_db_group_get_or_create(a_group);
    if (!l_tree) {
        fprintf(stderr, "Cannot open group '%s'\n", a_group);
        return 1;
    }

    dap_global_db_cursor_t *l_cur = dap_global_db_cursor_create(l_tree);
    if (!l_cur) {
        fprintf(stderr, "No records in group '%s'\n", a_group);
        return 0;
    }

    dap_global_db_read_begin(l_tree);

    int l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_FIRST, NULL);
    size_t l_count = 0;
    while (l_rc == 0) {
        char *l_text_key = NULL;
        void *l_value = NULL;
        uint32_t l_value_len = 0;
        uint8_t l_flags = 0;

        if (dap_global_db_cursor_get(l_cur, NULL, &l_text_key,
                                     &l_value, &l_value_len,
                                     NULL, NULL, &l_flags) == 0) {
            if (!(l_flags & DAP_GLOBAL_DB_RECORD_DEL)) {
                printf("%s\t%u\n", l_text_key ? l_text_key : "(null)", l_value_len);
                l_count++;
            }
            DAP_DEL_Z(l_text_key);
            DAP_DEL_Z(l_value);
        }
        l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_NEXT, NULL);
    }

    dap_global_db_read_end(l_tree);
    dap_global_db_cursor_close(l_cur);
    printf("Total: %zu\n", l_count);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: read                                                      */
/* ------------------------------------------------------------------ */

static int s_cmd_read(const char *a_group, const char *a_key)
{
    dap_global_db_t *l_tree = dap_global_db_group_get_or_create(a_group);
    if (!l_tree) {
        fprintf(stderr, "Cannot open group '%s'\n", a_group);
        return 1;
    }

    dap_global_db_read_begin(l_tree);
    dap_global_db_cursor_t *l_cur = dap_global_db_cursor_create(l_tree);
    if (!l_cur) {
        dap_global_db_read_end(l_tree);
        fprintf(stderr, "Record '%s/%s' not found (empty group)\n", a_group, a_key);
        return 1;
    }

    int l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_FIRST, NULL);
    bool l_found = false;
    while (l_rc == 0) {
        char *l_text_key = NULL;
        void *l_value = NULL;
        uint32_t l_value_len = 0;
        uint8_t l_flags = 0;

        if (dap_global_db_cursor_get(l_cur, NULL, &l_text_key,
                                     &l_value, &l_value_len,
                                     NULL, NULL, &l_flags) == 0) {
            if (l_text_key && strcmp(l_text_key, a_key) == 0 &&
                !(l_flags & DAP_GLOBAL_DB_RECORD_DEL)) {
                printf("group: %s\nkey: %s\nsize: %u\n", a_group, a_key, l_value_len);
                if (l_value && l_value_len) {
                    printf("value (hex): ");
                    for (uint32_t i = 0; i < l_value_len; i++)
                        printf("%02x", ((uint8_t *)l_value)[i]);
                    printf("\n");
                }
                l_found = true;
            }
            DAP_DEL_Z(l_text_key);
            DAP_DEL_Z(l_value);
        }
        if (l_found) break;
        l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_NEXT, NULL);
    }

    dap_global_db_read_end(l_tree);
    dap_global_db_cursor_close(l_cur);

    if (!l_found) {
        fprintf(stderr, "Record '%s/%s' not found\n", a_group, a_key);
        return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: delete                                                    */
/* ------------------------------------------------------------------ */

static int s_cmd_delete(const char *a_group, const char *a_key)
{
    dap_global_db_t *l_tree = dap_global_db_group_get_or_create(a_group);
    if (!l_tree) {
        fprintf(stderr, "Cannot open group '%s'\n", a_group);
        return 1;
    }

    dap_global_db_cursor_t *l_cur = dap_global_db_cursor_create(l_tree);
    if (!l_cur) {
        fprintf(stderr, "Record '%s/%s' not found\n", a_group, a_key);
        return 1;
    }

    dap_global_db_read_begin(l_tree);
    int l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_FIRST, NULL);
    dap_global_db_key_t l_found_key = {0};
    bool l_found = false;

    while (l_rc == 0) {
        dap_global_db_key_t l_cur_key;
        char *l_text_key = NULL;

        if (dap_global_db_cursor_get(l_cur, &l_cur_key, &l_text_key,
                                     NULL, NULL, NULL, NULL, NULL) == 0) {
            if (l_text_key && strcmp(l_text_key, a_key) == 0) {
                l_found_key = l_cur_key;
                l_found = true;
            }
            DAP_DEL_Z(l_text_key);
        }
        if (l_found) break;
        l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_NEXT, NULL);
    }
    dap_global_db_read_end(l_tree);
    dap_global_db_cursor_close(l_cur);

    if (!l_found) {
        fprintf(stderr, "Record '%s/%s' not found\n", a_group, a_key);
        return 1;
    }

    l_rc = dap_global_db_delete(l_tree, &l_found_key);
    if (l_rc) {
        fprintf(stderr, "Failed to delete '%s/%s', code %d\n", a_group, a_key, l_rc);
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

    dap_global_db_t *l_tree = dap_global_db_group_get_or_create(l_group);
    if (!l_tree) {
        fprintf(stderr, "Cannot open group '%s'\n", l_group);
        return 1;
    }

    dap_global_db_cursor_t *l_cur = dap_global_db_cursor_create(l_tree);
    if (!l_cur) {
        fprintf(stderr, "Group '%s' is empty\n", l_group);
        return 1;
    }

    dap_global_db_read_begin(l_tree);
    int l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_FIRST, NULL);
    dap_global_db_key_t l_found_key = {0};
    void *l_old_value = NULL;
    uint32_t l_old_value_len = 0;
    void *l_old_sign = NULL;
    uint32_t l_old_sign_len = 0;
    bool l_found = false;

    while (l_rc == 0) {
        dap_global_db_key_t l_cur_key;
        char *l_text_key = NULL;
        void *l_value = NULL;
        uint32_t l_value_len = 0;
        void *l_sign = NULL;
        uint32_t l_sign_len = 0;
        uint8_t l_flags = 0;

        if (dap_global_db_cursor_get(l_cur, &l_cur_key, &l_text_key,
                                     &l_value, &l_value_len,
                                     &l_sign, &l_sign_len, &l_flags) == 0) {
            if (l_text_key && strcmp(l_text_key, a_node_addr_str) == 0 &&
                !(l_flags & DAP_GLOBAL_DB_RECORD_DEL)) {
                l_found_key = l_cur_key;
                l_old_value = l_value;
                l_old_value_len = l_value_len;
                l_old_sign = l_sign;
                l_old_sign_len = l_sign_len;
                l_found = true;
                l_value = NULL;
                l_sign = NULL;
            }
            DAP_DEL_Z(l_text_key);
            DAP_DEL_Z(l_value);
            DAP_DEL_Z(l_sign);
        }
        if (l_found) break;
        l_rc = dap_global_db_cursor_move(l_cur, DAP_GLOBAL_DB_NEXT, NULL);
    }
    dap_global_db_read_end(l_tree);
    dap_global_db_cursor_close(l_cur);

    if (!l_found) {
        fprintf(stderr, "Record '%s/%s' not found\n", l_group, a_node_addr_str);
        return 1;
    }

    if (l_old_value_len < sizeof(gdb_node_info_t)) {
        fprintf(stderr, "Record too small (%u < %zu)\n",
                l_old_value_len, sizeof(gdb_node_info_t));
        DAP_DEL_Z(l_old_value);
        DAP_DEL_Z(l_old_sign);
        return 1;
    }

    gdb_node_info_t *l_old_info = (gdb_node_info_t *)l_old_value;

    size_t l_new_host_len = strlen(a_new_host);
    size_t l_new_size = sizeof(gdb_node_info_t) + l_new_host_len + 1;
    gdb_node_info_t *l_new_info = calloc(1, l_new_size);
    if (!l_new_info) {
        DAP_DEL_Z(l_old_value);
        DAP_DEL_Z(l_old_sign);
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

    DAP_DEL_Z(l_old_value);

    /* Delete old entry, insert new with same hash key to preserve ordering */
    dap_global_db_delete(l_tree, &l_found_key);

    /* Build new hash key from updated store object */
    dap_global_db_store_obj_t l_obj = {
        .group     = l_group,
        .key       = (char *)a_node_addr_str,
        .value     = (byte_t *)l_new_info,
        .value_len = l_new_size,
        .timestamp = dap_nanotime_now(),
        .flags     = 0,
        .sign      = NULL,
        .crc       = 0,
    };
    l_obj.crc = dap_global_db_store_obj_checksum(&l_obj);

    dap_global_db_hash_t l_hash = dap_global_db_hash_get(&l_obj);
    dap_global_db_key_t l_new_key = { .bets = l_hash.bets, .becrc = l_hash.becrc };

    size_t l_key_len = strlen(a_node_addr_str) + 1;
    l_rc = dap_global_db_insert(l_tree, &l_new_key,
                                a_node_addr_str, (uint32_t)l_key_len,
                                l_new_info, (uint32_t)l_new_size,
                                l_old_sign, l_old_sign_len,
                                0);

    if (l_rc == 0) {
        printf("OK %s/%s -> %s:%s\n", l_group, a_node_addr_str,
               a_new_host,
               a_new_port_str ? a_new_port_str : "unchanged");
    } else {
        fprintf(stderr, "Failed to write '%s/%s', code %d\n",
                l_group, a_node_addr_str, l_rc);
    }

    free(l_new_info);
    DAP_DEL_Z(l_old_sign);
    return l_rc ? 1 : 0;
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

    const char *l_db_path = NULL;
    int l_cmd_start = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--db-path") && i + 1 < argc) {
            l_db_path = argv[++i];
        } else if (!strcmp(argv[i], "--driver")) {
            /* Accepted but ignored — single native B-tree backend */
            i++;
        } else {
            l_cmd_start = i;
            break;
        }
    }

    if (!l_db_path || !l_cmd_start) {
        fprintf(stderr, "Error: --db-path is required\n\n");
        s_print_usage(argv[0]);
        return 1;
    }

    dap_common_init("dap-gdb-tool", NULL);
    dap_log_level_set(L_WARNING);

    int l_rc = dap_global_db_groups_init(l_db_path);
    if (l_rc) {
        fprintf(stderr, "Failed to initialize GDB at '%s', code %d\n",
                l_db_path, l_rc);
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

    dap_global_db_groups_flush();
    dap_global_db_groups_deinit();
    return l_ret;
}
