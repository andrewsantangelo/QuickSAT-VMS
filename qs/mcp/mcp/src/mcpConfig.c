
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#include "mcp.h"
#include "mcpConfig.h"

typedef enum McpConfigKeys_e {
    MCP_CONFIG_MCP_DIR = 0,
    MCP_CONFIG_MCT_FILENAME,
    MCP_CONFIG_XEN_DIR,
    MCP_CONFIG_XL_BIN,
    MCP_CONFIG_VMS_ENABLED,
    MCP_CONFIG_VMS_CONNECT_DELAY,
    MCP_CONFIG_VMS_CONNECT_RETRIES,
    MCP_CONFIG_VMS_ADDRESS,
    MCP_CONFIG_VMS_PORT,
    MCP_CONFIG_VMS_USERNAME,
    MCP_CONFIG_VMS_PASSWORD,
    MCP_CONFIG_VMS_SSL_CERT,
    MCP_CONFIG_VMS_DB_NAME,
    MCP_CONFIG_SIZE
} McpConfigKeys_t;

static const char *m_configKeys[MCP_CONFIG_SIZE] = {
    "home",
    "mct",
    "xen",
    "xl",
    "vms_enabled",
    "vms_connect_delay",
    "vms_connect_retries",
    "vms_address",
    "vms_port",
    "vms_username",
    "vms_password",
    "vms_ssl_cert",
    "vms_db_name"
};

/* Default configuration values */
static const McpConfigData_t m_configDefault = {
    .mcpDir            = MCP_DIR, /* a default "/etc/mcp" */
    .mctFilename       = MCP_DIR "/mct.db",
    .xenDir            = "/etc/xen",
    .xlBinLocation     = "/usr/sbin/xl",
    .vmsEnabled        = true,
    .vmsConnectDelay   = 0.0,
    .vmsConnectRetries = 0,
    .vmsAddress        = "localhost",
    .vmsPort           = 3306,
    .vmsUsername       = "root",
    .vmsPassword       = "root",
    .vmsSSLCert        = NULL,
    .vmsDBName         = "stepSATdb_Flight"
};

static McpConfigData_t m_config;

McpConfigData_t* mcpConfig_init(void) {
    char configKey[100];
    char configVal[100];
    bool found;
    char *line = NULL;
    size_t n = 0; /* required by getline(), even though it isn't used */
    char *values[MCP_CONFIG_SIZE] = { NULL };
    FILE *configFile = NULL;
    McpConfigKeys_t key;

    errno = 0;
    configFile = fopen(MCP_DIR "/mcp.conf", "r");
    if (NULL == configFile) {
        mcp_log(LOG_WARNING, "%s:%d unable to open MCP config \"%s\" (%d:%s)",
                __FUNCTION__, __LINE__, MCP_DIR "/mcp.conf",
                errno, strerror(errno));
    } else /* ! (NULL == configFile) */ {
        while (-1 != getline(&line, &n, configFile)) {
            /* Check for comments */
            if ('#' != line[0]) {
                if (EOF != sscanf(line, " %99s = %99s", configKey, configVal)) {
                    found = false;
                    for (key = 0; (key < MCP_CONFIG_SIZE) && (false == found); key++) {
                        if (0 == strcmp(m_configKeys[key], configKey)) {
                            values[key] = strdup(configVal);
                            found = true;
                        }
                    }
                }
            } /* if ('#' != line[0]) */

            free(line);
            line = NULL;
        } /* while (-1 != getline(&line, NULL, configFile)) */
    } /* else ! (NULL == configFile) */
    fclose(configFile);

    /* Use the default config value unless there is a value specified in the 
     * config file. */
    for (key = 0; key < MCP_CONFIG_SIZE; key++) {
        switch (key) {
        case MCP_CONFIG_MCP_DIR:
            if (NULL == values[key]) {
                m_config.mcpDir = strdup(m_configDefault.mcpDir);
            } else {
                m_config.mcpDir = values[key];
            }
            break;
        case MCP_CONFIG_MCT_FILENAME:
            if (NULL == values[key]) {
                m_config.mctFilename = strdup(m_configDefault.mctFilename);
            } else {
                m_config.mctFilename = values[key];
            }
            break;
        case MCP_CONFIG_XEN_DIR:
            if (NULL == values[key]) {
                m_config.xenDir = strdup(m_configDefault.xenDir);
            } else {
                m_config.xenDir = values[key];
            }
            break;
        case MCP_CONFIG_XL_BIN:
            if (NULL == values[key]) {
                m_config.xlBinLocation = strdup(m_configDefault.xlBinLocation);
            } else {
                m_config.xlBinLocation = values[key];
            }
            break;
        case MCP_CONFIG_VMS_ENABLED:
            if (NULL == values[key]) {
                m_config.vmsEnabled = m_configDefault.vmsEnabled;
            } else {
                /* handle a few common ways to state that a VMS connection 
                 * should be enabled. */
                if ((0 == strcasecmp("true", values[key]))
                    || ('1' == values[key][0])) {
                        m_config.vmsEnabled = true;
                } else {
                    m_config.vmsEnabled = false;
                }
            }
            break;
        case MCP_CONFIG_VMS_CONNECT_DELAY:
            if (NULL == values[key]) {
                m_config.vmsConnectDelay = m_configDefault.vmsConnectDelay;
            } else {
                m_config.vmsConnectDelay = (double)strtod(values[key], NULL);
                /* Since only the value in the string is required, free the 
                 * string now */
                free(values[key]);
            }
            break;
        case MCP_CONFIG_VMS_CONNECT_RETRIES:
            if (NULL == values[key]) {
                m_config.vmsConnectRetries = m_configDefault.vmsConnectRetries;
            } else {
                m_config.vmsConnectRetries = (uint32_t)strtoul(values[key], NULL, 10);
                /* Since only the value in the string is required, free the 
                 * string now */
                free(values[key]);
            }
            break;
        case MCP_CONFIG_VMS_ADDRESS:
            if (NULL == values[key]) {
                m_config.vmsAddress = strdup(m_configDefault.vmsAddress);
            } else {
                m_config.vmsAddress = values[key];
            }
            break;
        case MCP_CONFIG_VMS_PORT:
            if (NULL == values[key]) {
                m_config.vmsPort = m_configDefault.vmsPort;
            } else {
                m_config.vmsPort = (uint16_t)strtoul(values[key], NULL, 10);
                /* Since only the value in the string is required, free the 
                 * string now */
                free(values[key]);
            }
            break;
        case MCP_CONFIG_VMS_USERNAME:
            if (NULL == values[key]) {
                m_config.vmsUsername = strdup(m_configDefault.vmsUsername);
            } else {
                m_config.vmsUsername = values[key];
            }
            break;
        case MCP_CONFIG_VMS_PASSWORD:
            if (NULL == values[key]) {
                m_config.vmsPassword = strdup(m_configDefault.vmsPassword);
            } else {
                m_config.vmsPassword = values[key];
            }
            break;
        case MCP_CONFIG_VMS_SSL_CERT:
            if (NULL == values[key]) {
                /* This value can be NULL, so see if the default is NULL before 
                 * blindly attempting to copy it. */
                if (NULL != m_configDefault.vmsSSLCert) {
                    m_config.vmsSSLCert = strdup(m_configDefault.vmsSSLCert);
                } else {
                    m_config.vmsSSLCert = NULL;
                }
            } else {
                m_config.vmsSSLCert = values[key];
            }
            break;
        case MCP_CONFIG_VMS_DB_NAME:
            if (NULL == values[key]) {
                m_config.vmsDBName = strdup(m_configDefault.vmsDBName);
            } else {
                m_config.vmsDBName = values[key];
            }
            break;
        default:
            /* do nothing for unexpected values */
            break;
        } /* switch (key) */
    } /* for (key = 0; key < MCP_CONFIG_SIZE; key++) */

    return &m_config;
} /* McpConfigData_t* mcpConfig_init(void) */

McpConfigData_t* mcpConfig_get() {
    return &m_config;
} /* McpConfigData_t* mcpConfig_get() */

void mcpConfig_close(void) {
    /* Free the config values that are strings */
    free(m_config.mcpDir);
    free(m_config.mctFilename);
    free(m_config.xenDir);
    free(m_config.xlBinLocation);
    free(m_config.vmsAddress);
    free(m_config.vmsUsername);
    free(m_config.vmsPassword);

    /* This option is allowed to be NULL */
    if (NULL != m_config.vmsSSLCert) {
        free(m_config.vmsSSLCert);
    }

    free(m_config.vmsDBName);
} /* void mcpConfig_close(void) */

