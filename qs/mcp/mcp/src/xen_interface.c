
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#include <xenctrl.h>
#include <xenstore.h>

#include "mcp.h"

#include "xen_interface.h"

/* Define the xen handle structure */
struct XenInfoHandle_s {
    uint32_t            info_size;
    xc_domaininfo_t     *info;
};

static struct xs_handle    *xsh = NULL;
static xc_interface        *xci = NULL;

bool xen_open(void) {
    bool success = false;

    errno = 0;
    xsh = xs_open(XS_OPEN_READONLY);
    if (NULL != xsh) {
        errno = 0;
        xci = xc_interface_open(NULL, NULL, 0);
        if (NULL != xci) {
            success = true;
        } else {
            mcp_log(LOG_ERR, "%s:%d xc_interface_open() error (%d:%s)",
                    __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        mcp_log(LOG_ERR, "%s:%d xs_open() error (%d:%s)",
                __FUNCTION__, __LINE__, errno, strerror(errno));
    }

    if (true != success) {
        xen_close();
    }

    return success;
} /* bool xen_open(void) */

void xen_close(void) {
    if (NULL != xci) {
        xc_interface_close(xci);
    }

    if (NULL != xsh) {
        xs_close(xsh);
    }
} /* void xen_close(void) */

XenDomState_t xen_getDomState(struct XenInfoHandle_s *handle, char *name, domid_t *id) {
    XenDomState_t state = XEN_DOM_UNKNOWN;
    int32_t match = -1;
    char *domname = NULL;

    if (NULL != handle) {
        if (NULL != handle->info) {
            if ((NULL != id) && (DOMID_INVALID != *id)) {
                /* Match by ID (less costly comparison operation since it isn't
                 * necessary to make another Xen API call). */
                for (uint32_t i = 0; (i < handle->info_size) && (-1 == match); i++) {
                    if (handle->info[i].domain == *id) {
                        match = i;
                    }
                }
            } else if (NULL != name) {
                /* Match by domain name */
                for (uint32_t i = 0; (i < handle->info_size) && (-1 == match); i++) {
                    domname = xen_getDomName(handle->info[i].domain);
                    if (NULL != domname) {
                        if (0 == strcmp(domname, name)) {
                            match = i;

                            /* If the domain is being matched by the domain 
                             * name, and a pointer to an ID variable is 
                             * provided, return the ID for the matched domain by 
                             * reference. */
                            if (NULL != id) {
                                *id = handle->info[match].domain;
                            }
                        } /* if (0 == strcmp(domname, name)) */
                        free(domname);
                    } /* if (NULL != domname) */
                } /* for (uint32_t i = 0; (i < handle->info_size) && (-1 == match); i++) */
            } else {
                mcp_log(LOG_WARNING, "%s:%d invalid domain match criteria",
                        __FUNCTION__, __LINE__);
            }

            /* If a match was found, determine the state of the matched domain */
            if ((0 <= match) && ((int32_t)handle->info_size > match)) {
                state = xen_domStateFromFlags(handle->info[match].flags);
            } else {
                mcp_log(LOG_WARNING, "%s:%d unable to find matching domain (%s/%d)",
                        __FUNCTION__, __LINE__, name, match);
            }
        } else { /* ! (NULL != handle->info) */
            mcp_log(LOG_WARNING, "%s:%d invalid info handle", __FUNCTION__, __LINE__);
        }
    } else { /* ! (NULL != handle) */
        mcp_log(LOG_WARNING, "%s:%d invalid handle", __FUNCTION__, __LINE__);
    }

    return state;
} /* XenDomState_t xen_getDomState(struct XenInfoHandle_s *handle, char *name, domid_t *id) */

domid_t xen_getDomID(struct XenInfoHandle_s *handle, char *name) {
    domid_t match = DOMID_INVALID;
    char *domname = NULL;
    bool success = false;

    if (NULL != handle) {
        if (NULL != handle->info) {
            success = true;
        } else {
            mcp_log(LOG_WARNING, "%s:%d invalid domain info", __FUNCTION__, __LINE__);
        }
    } else {
        mcp_log(LOG_WARNING, "%s:%d invalid handle", __FUNCTION__, __LINE__);
    }

    if (true == success) {
        /* Loop through the information for each domain and locate the one with 
         * the matching name */
        for (uint32_t i = 0; (i < handle->info_size) && (DOMID_INVALID == match); i++) {
            domname = xen_getDomName(handle->info[i].domain);
            if (NULL != domname) {
                if (0 == strcmp(domname, name)) {
                    match = handle->info[i].domain;
                }
                free(domname);
            } else {
                mcp_log(LOG_ERR, "%s:%d failed to retrieve domain name for info[%u] = %u",
                        __FUNCTION__, __LINE__, i, handle->info[i].domain);
            }
        }

        /* If a match was found, determine the state of the matched domain */
        if (DOMID_INVALID == match) {
            mcp_log(LOG_ERR, "%s:%d unable to find matching domain (%s)",
                    __FUNCTION__, __LINE__, name);
        }
    }

    return match;
} /* domid_t xen_getDomID(struct XenInfoHandle_s *handle, char *name) */

char *xen_getDomName(domid_t id) {
    char *name = NULL;
    char path[100];
    uint32_t len;

    if (NULL != xsh) {
        snprintf(path, sizeof(path), "/local/domain/%d/name", id);

        errno = 0;
        name = xs_read(xsh, XBT_NULL, path, &len);
        if (NULL == name) {
            mcp_log(LOG_ERR, "%s:%d xs_read(%s) error (%d:%s)",
                    __FUNCTION__, __LINE__, path, errno, strerror(errno));
        }
    } else {
        mcp_log(LOG_WARNING, "%s:%d invalid xen store handle", __FUNCTION__, __LINE__);
    }

    return name;
} /* char *xen_getDomName(domid_t id) */

XenDomState_t xen_domStateFromFlags(uint32_t flags) {
    XenDomState_t state;

    if (XEN_DOMINF_dying & flags) {
        state = XEN_DOM_DYING;
    } else if (XEN_DOMINF_shutdown & flags) {
        state = XEN_DOM_SHUTDOWN;
    } else if (XEN_DOMINF_paused & flags) {
        state = XEN_DOM_PAUSED;
    } else if (XEN_DOMINF_blocked & flags) {
        state = XEN_DOM_BLOCKED;
    } else if (XEN_DOMINF_running & flags) {
        state = XEN_DOM_RUNNING;
    } else {
        state = XEN_DOM_UNKNOWN;
    }

    return state;
} /* XenDomState_t xen_domStateFromFlags(uint32_t flags) */

struct XenInfoHandle_s* xen_getDomInfo(uint32_t info_start, uint32_t info_size) {
    struct XenInfoHandle_s *handle = NULL;
    int32_t num_doms;
    bool success = false;

    if (NULL != xci) {
        errno = 0;
        handle = (struct XenInfoHandle_s*)malloc(sizeof(struct XenInfoHandle_s));
        if (NULL != handle) {
            /* The info array will be added later */
            handle->info_size = 0;
            handle->info = NULL;

            /* Allocate the amount of info requested, make sure to have this be a signed
             * operation to guard against bad input values. */
            num_doms = (int32_t)info_size - (int32_t)info_start;
            if (0 < num_doms) {
                errno = 0;
                handle->info = (xc_domaininfo_t*) calloc(num_doms, sizeof(xc_domaininfo_t));

                if (NULL != handle->info) {
                    errno = 0;
                    num_doms = xc_domain_getinfolist(xci, info_start, info_size, handle->info);

                    if (0 < num_doms) {
                        /* the info was retrieved properly, set the success flag to 
                         * true and save the size of the data that was retrieved. */
                        handle->info_size = num_doms;
                        success = true;
                    } else {
                        mcp_log(LOG_ERR, "%s:%d xc_domain_getinfolist(%u, %u) returned %d (%d:%s)",
                                __FUNCTION__, __LINE__, info_size, info_start, num_doms,
                                errno, strerror(errno));
                    }
                } else { /* ! (NULL != info) */
                    mcp_log(LOG_ERR, "%s:%d malloc() error (%d:%s)",
                            __FUNCTION__, __LINE__, errno, strerror(errno));
                }
            } else { /* ! (0 < num_doms) */
                mcp_log(LOG_WARNING, "%s:%d invalid info size requested (start %u - size %u = %d)",
                        __FUNCTION__, __LINE__, info_start, info_size, num_doms);
            }
        } else { /* ! (NULL != handle) */
            mcp_log(LOG_ERR, "%s:%d malloc() error (%d:%s)",
                    __FUNCTION__, __LINE__, errno, strerror(errno));
        }

        /* If the info could not be retrieved, free the data that was allocated */
        if (true != success) {
            xen_releaseHandle(handle);
            handle = NULL;
        }
    } else { /* ! (NULL != xci) */
        mcp_log(LOG_WARNING, "%s:%d invalid xen interface handle", __FUNCTION__, __LINE__);
    }

    return handle;
} /* struct XenInfoHandle_s* xen_getDomInfo(uint32_t info_start, uint32_t info_size) */

void xen_releaseHandle(struct XenInfoHandle_s* handle) {
    if (NULL != handle) {
        if (NULL != handle->info) {
            free(handle->info);
        }
        free(handle);
    }
} /* void xen_releaseHandle(struct XenInfoHandle_s* handle) */

