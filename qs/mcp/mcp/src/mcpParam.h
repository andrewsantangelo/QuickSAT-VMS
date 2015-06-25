
#ifndef __MCP_PARAM_H__
#define __MCP_PARAM_H__

bool mcpParam_initialize(void);
void mcpParam_shutdown(void);

bool mcpParam_valid(uint32_t id);
bool mcpParam_set(uint32_t id, double value);
bool mcpParam_get(uint32_t id, double *value);

#endif /* __MCP_PARAM_H__ */

