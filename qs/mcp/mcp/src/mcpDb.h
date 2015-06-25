
#ifndef __MCP_DB_H__
#define __MCP_DB_H__

typedef struct McpSharedData_s {
    sem_t           sem;
    uint32_t        mcpState;
    uint32_t        opMode;
    uint32_t        flightLeg;
    uint32_t        numParams;
    double          params[];
} McpSharedData_t;

extern sqlite3          *g_mct;
extern McpSharedData_t  *g_mcpShm;
extern sem_t            *g_mcpShmSem;

#endif /* __MCP_DB_H__ */

