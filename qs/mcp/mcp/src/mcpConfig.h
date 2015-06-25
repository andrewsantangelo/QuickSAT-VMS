
#ifndef __MCP_CONFIG_H__
#define __MCP_CONFIG_H__

typedef struct McpConfigData_s {
    char    *mcpDir;
    char    *mctFilename;
    char    *xenDir;
    char    *xlBinLocation;
    bool     vmsEnabled;
    double  vmsConnectDelay;
    uint32_t vmsConnectRetries;
    char    *vmsAddress;
    uint16_t vmsPort;
    char    *vmsUsername;
    char    *vmsPassword;
    char    *vmsSSLCert;
    char    *vmsDBName;
} McpConfigData_t;

McpConfigData_t* mcpConfig_init(void);
McpConfigData_t* mcpConfig_get(void);
void mcpConfig_close(void);

#endif /* __MCP_CONFIG_H__ */

