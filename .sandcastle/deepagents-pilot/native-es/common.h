#ifndef MAINTENANCE_ES_COMMON_H
#define MAINTENANCE_ES_COMMON_H
#include <Security/Security.h>
#include <bsm/audit.h>
#include <stdbool.h>
#include <stdio.h>
#define FIELD 129
bool token_ok(const char *s);
bool peer_token(int fd, audit_token_t *token);
SecRequirementRef requirement_file(const char *path);
bool signed_code(const audit_token_t *token, SecRequirementRef requirement);
void json_token(FILE *out, audit_token_t token);
int socket_connect(const char *path);
int scheduler_identity(const char *socket_path, const char *collector_requirement, audit_token_t *identity);
bool write_all(int fd, const char *s);
int read_line(int fd, char *buffer, size_t capacity);
#endif
