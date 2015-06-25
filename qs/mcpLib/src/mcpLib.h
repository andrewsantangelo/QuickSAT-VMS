
#ifndef __MCP_LIB_H__
#define __MCP_LIB_H__

#define MODE_HALTED 0

bool mcpLib_open(char *dbfile);
void mcpLib_close(void);
bool mcpLib_getFlightLeg(uint32_t *leg);
bool mcpLib_getOpMode(uint32_t *mode);
bool mcpLib_getMcpState(uint32_t *state);
bool mcpLib_getAllShmStateData(uint32_t *flightLeg, uint32_t *opMode, uint32_t *mcpState);
bool mcpLib_setParam(uint32_t id, double value);
bool mcpLib_getParam(uint32_t id, double *value);
bool mcpLib_getRule(uint32_t id, char **name, char **str);

#endif /* __MCP_LIB_H__ */

