/* Development-only single ES client. stdout is the ordered reducer channel, never model output. */
#include "common.h"
#include <EndpointSecurity/EndpointSecurity.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <uuid/uuid.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static es_client_t *client;
static SecRequirementRef helper_requirement;
static bool healthy = false, have_seq = false;
static uint64_t last_seq;
static char epoch[37], image[FIELD];
static uid_t helper_uid;
static int listener;
static es_event_type_t subscribed[] = { ES_EVENT_TYPE_NOTIFY_FORK, ES_EVENT_TYPE_NOTIFY_EXEC, ES_EVENT_TYPE_NOTIFY_EXIT };
#define CONNECTIONS 64
struct connection { int fd; bool registered, armed, started, waited, receipt_acked; pid_t primary; audit_token_t peer; char resource[FIELD], nonce[FIELD]; };
static struct connection connections[CONNECTIONS];

static void flush_output(void) { if (ferror(stdout) || fflush(stdout)) _exit(74); }
static void lost(const char *reason) {
    healthy = false;
    output(stdout, "{\"type\":\"lost\",\"epoch\":\"%s\",\"reason\":\"%s\"}\n", epoch, reason);
    flush_output();
}
static bool lifecycle(es_event_type_t event) {
    return event == subscribed[0] || event == subscribed[1] || event == subscribed[2];
}
static bool coverage(void) {
    for (int type = ES_MUTE_INVERSION_TYPE_PROCESS; type < ES_MUTE_INVERSION_TYPE_LAST; type++)
        if (es_muting_inverted(client, (es_mute_inversion_type_t)type) != ES_MUTE_NOT_INVERTED) return false;
    size_t count = 0; es_event_type_t *events = NULL;
    if (es_subscriptions(client, &count, &events) != ES_RETURN_SUCCESS) return false;
    bool ok = count == 3;
    unsigned mask = 0;
    for (size_t i = 0; i < count; i++) {
        if (!lifecycle(events[i])) ok = false;
        for (unsigned j = 0; j < 3; j++) if (events[i] == subscribed[j]) mask |= 1u << j;
    }
    free(events);
    if (!ok || mask != 7) return false;
    es_muted_paths_t *paths = NULL;
    if (es_muted_paths_events(client, &paths) != ES_RETURN_SUCCESS || !paths) return false;
    for (size_t i = 0; i < paths->count; i++)
        for (size_t j = 0; j < paths->paths[i].event_count; j++)
            if (lifecycle(paths->paths[i].events[j])) ok = false;
    es_release_muted_paths(paths);
    es_muted_processes_t *processes = NULL;
    if (es_muted_processes_events(client, &processes) != ES_RETURN_SUCCESS || !processes) return false;
    for (size_t i = 0; i < processes->count; i++)
        for (size_t j = 0; j < processes->processes[i].event_count; j++)
            if (lifecycle(processes->processes[i].events[j])) ok = false;
    es_release_muted_processes(processes);
    return ok;
}
static void receive_event(const es_message_t *message) {
    pthread_mutex_lock(&lock);
    if (!healthy) { pthread_mutex_unlock(&lock); return; }
    /* Before any event-specific branch, including unrelated system processes. */
    if (message->version < 5 || (have_seq && message->global_seq_num != last_seq + 1)) {
        lost("internal_drop"); pthread_mutex_unlock(&lock); return;
    }
    if (!coverage()) { lost("configuration_changed"); pthread_mutex_unlock(&lock); return; }
    last_seq = message->global_seq_num; have_seq = true;
    const audit_token_t *target = NULL;
    const char *kind = NULL, *alias = NULL;
    switch (message->event_type) {
    case ES_EVENT_TYPE_NOTIFY_FORK: kind = "FORK"; target = &message->event.fork.child->audit_token; break;
    case ES_EVENT_TYPE_NOTIFY_EXEC:
        kind = "EXEC"; target = &message->event.exec.target->audit_token;
        alias = signed_code(target, helper_requirement) ? image : "other-executable";
        break;
    case ES_EVENT_TYPE_NOTIFY_EXIT: kind = "EXIT"; break;
    default: lost("internal_drop"); pthread_mutex_unlock(&lock); return;
    }
    output(stdout, "{\"type\":\"event\",\"event\":{\"epoch\":\"%s\",\"seq\":%llu,\"version\":%u,\"kind\":\"%s\",\"actor\":", epoch, (unsigned long long)last_seq, message->version, kind);
    json_token(stdout, message->process->audit_token);
    fputs(",\"target\":", stdout); if (target) json_token(stdout, *target); else fputs("null", stdout);
    if (alias) output(stdout, ",\"image\":\"%s\"}}\n", alias); else fputs(",\"image\":null}}\n", stdout);
    flush_output(); pthread_mutex_unlock(&lock);
}
static bool same_peer(struct connection *c) {
    audit_token_t current;
    return peer_token(c->fd, &current) && !memcmp(&current, &c->peer, sizeof(current)) &&
        signed_code(&current, helper_requirement);
}
static void *connection_worker(void *arg) {
    struct connection *c = arg;
    char line[1024], parts[3][FIELD];
    if (read_line(c->fd, line, sizeof(line)) < 0) goto done;
    if (!strcmp(line, "IDENTITY")) {
        /* Read-only caller identity; this grants no helper signature status or ARM. */
        audit_token_t peer;
        if (peer_token(c->fd, &peer) && !memcmp(&peer, &c->peer, sizeof(peer)) && peer.val[1] == helper_uid) {
            char response[256];
            if (!format(response, sizeof(response), "IDENTITY %u %u %u %u %u %u %u %u\n",
                peer.val[0], peer.val[1], peer.val[2], peer.val[3], peer.val[4], peer.val[5], peer.val[6], peer.val[7])) goto done;
            write_all(c->fd, response);
        }
        goto done;
    }
    pthread_mutex_lock(&lock);
    bool ok = healthy && same_peer(c) &&
        fields(line, "REGISTER", parts, 3) && !strcmp(parts[2], image);
    if (ok) { strlcpy(c->resource, parts[0], FIELD); strlcpy(c->nonce, parts[1], FIELD); }
    for (size_t i = 0; i < CONNECTIONS; i++)
        if (&connections[i] != c && connections[i].fd >= 0 && connections[i].registered &&
            (!strcmp(connections[i].resource, c->resource) || !strcmp(connections[i].nonce, c->nonce))) ok = false;
    if (ok) {
        c->registered = true;
        output(stdout, "{\"type\":\"register\",\"resource\":\"%s\",\"nonce\":\"%s\",\"image\":\"%s\",\"peer\":", c->resource, c->nonce, image);
        json_token(stdout, c->peer); fputs("}\n", stdout); flush_output();
    }
    pthread_mutex_unlock(&lock);
    if (!ok) goto done;
    while (read_line(c->fd, line, sizeof(line)) >= 0) {
        uint32_t pid = 0, code = 0;
        pthread_mutex_lock(&lock);
        if (!same_peer(c) || !c->armed) { lost("internal_drop"); pthread_mutex_unlock(&lock); break; }
        if (!c->started && fields(line, "START", parts, 1) && decimal(parts[0], INT_MAX, &pid) && pid > 0) {
            c->started = true; c->primary = pid;
            output(stdout, "{\"type\":\"started\",\"resource\":\"%s\",\"pid\":%u}\n", c->resource, pid);
        } else if (c->started && !c->waited && fields(line, "WAIT", parts, 2) && decimal(parts[0], INT_MAX, &pid) &&
                   decimal(parts[1], 255, &code) && pid == (uint32_t)c->primary) {
            c->waited = true;
            output(stdout, "{\"type\":\"waited\",\"resource\":\"%s\",\"pid\":%u,\"code\":%u}\n", c->resource, pid, code);
        } else { lost("internal_drop"); pthread_mutex_unlock(&lock); break; }
        flush_output(); pthread_mutex_unlock(&lock);
    }
 done:
    pthread_mutex_lock(&lock);
    if (c->registered && !c->waited) lost("source_lost");
    close(c->fd); c->fd = -1; /* Durable replay authority stays in reducer, not this reusable fd slot. */
    pthread_mutex_unlock(&lock);
    return NULL;
}
static void *accept_connections(void *unused) {
    (void)unused;
    while (true) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) { if (errno == EINTR) continue; break; }
        fcntl(fd, F_SETFD, FD_CLOEXEC);
        audit_token_t peer;
        if (!peer_token(fd, &peer) || peer.val[1] != helper_uid) { close(fd); continue; }
        pthread_mutex_lock(&lock);
        struct connection *c = NULL;
        for (size_t i = 0; i < CONNECTIONS; i++) if (connections[i].fd == -1) { c = &connections[i]; break; }
        if (c) { memset(c, 0, sizeof(*c)); c->fd = fd; c->peer = peer; }
        pthread_mutex_unlock(&lock);
        if (!c) { close(fd); continue; }
        pthread_t thread;
        if (pthread_create(&thread, NULL, connection_worker, c)) { close(fd); _exit(74); }
        pthread_detach(thread);
    }
    pthread_mutex_lock(&lock); lost("source_lost"); pthread_mutex_unlock(&lock);
    return NULL;
}
int main(int argc, char **argv) {
    /* Explicit dev invocation only: socket self.req helper.req alias uid */
    if (argc != 7 || strcmp(argv[1], "--development-only")) { fputs("maintenance_es_collector: disabled\n", stderr); return 78; }
    if (geteuid() != 0 || !token_ok(argv[5]) || !strcmp(argv[5], "other-executable")) { fputs("privilege_or_config_unverified\n", stderr); return 78; }
    uint32_t uid;
    if (!decimal(argv[6], UINT32_MAX, &uid)) return 78;
    helper_uid = (uid_t)uid; strlcpy(image, argv[5], sizeof(image));
    SecRequirementRef self = requirement_file(argv[3]);
    helper_requirement = requirement_file(argv[4]);
    if (!signed_code(NULL, self) || !helper_requirement) { fputs("signature_unverified\n", stderr); return 78; }
    signal(SIGPIPE, SIG_IGN);
    uuid_t id; uuid_generate_random(id); uuid_unparse_lower(id, epoch);
    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    if (argv[2][0] != '/' || strnlen(argv[2], sizeof(addr.sun_path)) >= sizeof(addr.sun_path)) return 78;
    char parent[sizeof(addr.sun_path)]; strlcpy(parent, argv[2], sizeof(parent));
    char *slash = strrchr(parent, '/'); if (!slash || slash == parent || !slash[1]) return 78;
    char socket_name[sizeof(addr.sun_path)]; strlcpy(socket_name, slash + 1, sizeof(socket_name)); *slash = 0;
    if (!strcmp(socket_name, ".") || !strcmp(socket_name, "..")) return 78;
    int directory = open(parent, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    struct stat st;
    if (directory < 0 || fstat(directory, &st) || st.st_uid != 0 || (st.st_mode & 0022) || fchdir(directory)) return 78;
    /* Bind/cleanup relative to the validated directory, not a re-resolved mutable ancestor path. */
    strlcpy(addr.sun_path, socket_name, sizeof(addr.sun_path));
    umask(0077); listener = socket(AF_UNIX, SOCK_STREAM, 0);
    if (listener < 0) return 78;
    if (bind(listener, (struct sockaddr *)&addr, sizeof(addr))) { close(listener); return 78; }
    if (fchownat(directory, socket_name, helper_uid, (gid_t)-1, AT_SYMLINK_NOFOLLOW) || listen(listener, 16)) {
        close(listener); unlinkat(directory, socket_name, 0); return 78;
    }
    for (size_t i = 0; i < CONNECTIONS; i++) connections[i].fd = -1;
    es_new_client_result_t result = es_new_client(&client, ^(es_client_t *c, const es_message_t *m) { (void)c; receive_event(m); });
    if (result != ES_NEW_CLIENT_RESULT_SUCCESS) {
        output(stderr, "es_client_unavailable:%d\n", result); close(listener); unlinkat(directory, socket_name, 0); return 78;
    }
    pthread_mutex_lock(&lock);
    if (es_subscribe(client, subscribed, 3) != ES_RETURN_SUCCESS || !coverage()) {
        lost("configuration_changed"); pthread_mutex_unlock(&lock); es_delete_client(client); close(listener); unlinkat(directory, socket_name, 0); return 78;
    }
    healthy = true;
    output(stdout, "{\"type\":\"source\",\"epoch\":\"%s\",\"protocol\":\"macos-es-v1\"}\n", epoch); flush_output();
    pthread_mutex_unlock(&lock);
    pthread_t acceptor; if (pthread_create(&acceptor, NULL, accept_connections, NULL)) return 74;
    char line[1024], parts[3][FIELD];
    while (read_line(STDIN_FILENO, line, sizeof(line)) >= 0) {
        pthread_mutex_lock(&lock);
        if (fields(line, "WAITED", parts, 2)) {
            bool found = false;
            for (size_t i = 0; i < CONNECTIONS; i++) {
                struct connection *c = &connections[i];
                if (c->fd >= 0 && c->waited && !c->receipt_acked && !strcmp(c->resource, parts[0]) && !strcmp(c->nonce, parts[1]) && same_peer(c)) {
                    c->receipt_acked = true; found = true;
                    if (!write_all(c->fd, "RECORDED\n")) lost("source_lost");
                    break;
                }
            }
            if (!found) lost("internal_drop");
            pthread_mutex_unlock(&lock); continue;
        }
        bool valid = fields(line, "ARM", parts, 3);
        if (!valid || !healthy || !have_seq || !coverage()) { lost("configuration_changed"); pthread_mutex_unlock(&lock); break; }
        bool found = false;
        for (size_t i = 0; i < CONNECTIONS; i++) {
            struct connection *c = &connections[i];
            if (c->fd >= 0 && c->registered && !strcmp(c->resource, parts[0]) && !strcmp(c->nonce, parts[1])) {
                found = true;
                if (c->armed || !same_peer(c)) { lost("internal_drop"); break; }
                c->armed = true; /* Record before write. Lost ACK never authorizes reconnect. */
                char ack[256];
                if (!format(ack, sizeof(ack), "ARM %s\n", parts[2])) { lost("internal_drop"); break; }
                if (!write_all(c->fd, ack)) lost("source_lost");
                break;
            }
        }
        if (!found) lost("internal_drop");
        pthread_mutex_unlock(&lock);
    }
    pthread_mutex_lock(&lock); lost("source_lost"); pthread_mutex_unlock(&lock);
    es_delete_client(client); close(listener); unlinkat(directory, socket_name, 0);
    /* No child signals: already armed helpers continue natural wait even after IPC EOF. */
    return 78;
}
