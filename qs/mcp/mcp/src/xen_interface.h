
#ifndef __XEN_INTERFACE_H__
#define __XEN_INTERFACE_H__

typedef enum XenDomState_e {
    XEN_DOM_UNKNOWN = 0,
    XEN_DOM_DYING,
    XEN_DOM_SHUTDOWN,
    XEN_DOM_PAUSED,
    XEN_DOM_BLOCKED,
    XEN_DOM_RUNNING
} XenDomState_t;

struct XenInfoHandle_s;

bool xen_open(void);
void xen_close(void);
XenDomState_t xen_getDomState(struct XenInfoHandle_s *handle, char *name, domid_t *id);
domid_t xen_getDomID(struct XenInfoHandle_s *handle, char *name);
char *xen_getDomName(domid_t id);
XenDomState_t xen_domStateFromFlags(uint32_t flags);
struct XenInfoHandle_s* xen_getDomInfo(uint32_t info_start, uint32_t info_size);
void xen_releaseHandle(struct XenInfoHandle_s* handle);

#endif /* __XEN_INTERFACE_H__ */

