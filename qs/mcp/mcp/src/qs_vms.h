
#ifndef __QS_VMS_H__
#define __QS_VMS_H__

typedef enum VmState_e {
    QS_VMS_VM_UNKNOWN,
    QS_VMS_VM_STARTED,
    QS_VMS_VM_PAUSED,
    QS_VMS_VM_ERROR,
} VmState_t;

bool vms_open(char *address, uint16_t port, char *username, char *password, char *ca_cert, char *db_name);
void vms_close(void);
bool vms_increment_session(void);
bool vms_status_update(char *message);
bool vms_param_update(uint32_t id, double val);
bool vms_set_vm_state(char *name, VmState_t state);

#endif /* __QS_VMS_H__ */

