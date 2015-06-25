
#ifndef __MCP_DOM_CTRL_H__
#define __MCP_DOM_CTRL_H__

typedef enum McpDomState_e {
    DOM_STATE_OFF = 0,
    DOM_STATE_ON,
    DOM_STATE_PAUSED,
    DOM_STATE_UNPAUSED,
    DOM_STATE_RESET,
    DOM_STATE_DELETE,       /* Indicates a domain has been destroyed */
    DOM_STATE_INIT,         /* Indicates a domain needs to be created */
} McpDomState_t;

bool mcpDC_initialize(void);
void mcpDC_shutdown(void);
bool mcpDC_reloadConfig(void);
bool mcpDC_setDomState(uint32_t id, McpDomState_t state);
bool mcpDC_getDomState(uint32_t id, McpDomState_t *state);
bool mcpDC_setSchedule(uint32_t sched);
bool mcpDC_getStatus(uint32_t size, char *buffer);
bool mcpDC_checkDomState(void);

#endif /* __MCP_DOM_CTRL_H__ */

