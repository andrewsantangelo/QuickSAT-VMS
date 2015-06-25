
#ifndef __MCP_RULES_H__
#define __MCP_RULES_H__

bool mcpRules_initialize(void);
void mcpRules_shutdown(void);

bool mcpRules_stop(uint32_t curState, uint32_t newState);
bool mcpRules_start(uint32_t newState, uint32_t curState);
void mcpRules_exec(union sigval data);

#endif /* __MCP_RULES_H__ */

