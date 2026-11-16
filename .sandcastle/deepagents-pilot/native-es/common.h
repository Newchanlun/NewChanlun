#ifndef MAINTENANCE_ES_COMMON_H
#define MAINTENANCE_ES_COMMON_H
#include <Security/Security.h>
#include <bsm/audit.h>
#include <stdbool.h>
#include <stdio.h>
#define FIELD 129
#define FRAME 2048
bool fields(const char *line, const char *verb, char values[][FIELD], size_t count);
bool decimal(const char *text, uint32_t maximum, uint32_t *value);
/* snprintf keeps compiler format checking at each literal call site. Always check
 * its signed result before writing; no truncated frame is ever sent. Arguments
 * buffer/capacity must be side-effect-free (all callers use local arrays). */
bool formatted(char *buffer, size_t capacity, int length);
void write_formatted(FILE *stream, const char *buffer, size_t capacity, int length);
#define format(buffer, capacity, ...) formatted(buffer, capacity, snprintf(buffer, capacity, __VA_ARGS__))
#define output(stream, ...) do { \
    char frame_buffer[FRAME]; \
    int frame_length = snprintf(frame_buffer, sizeof(frame_buffer), __VA_ARGS__); \
    write_formatted(stream, frame_buffer, sizeof(frame_buffer), frame_length); \
} while (0)
bool token_ok(const char *s);
bool peer_token(int fd, audit_token_t *token);
SecRequirementRef requirement_file(const char *path);
bool signed_code(const audit_token_t *token, SecRequirementRef requirement);
void json_token(FILE *out, audit_token_t token);
int socket_connect(const char *path);
int scheduler_identity(const char *socket_path, const char *collector_requirement, audit_token_t *identity);
int session_connect(const char *socket_path, const char *collector_requirement,
                    const char *resource, const char *nonce, const char *image);
bool write_all(int fd, const char *s);
int read_line(int fd, char *buffer, size_t capacity);
#endif
