/* No ES client here. Before ARM: connect, authenticate, register, block. */
#include "common.h"
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static volatile sig_atomic_t primary_pid;
static volatile sig_atomic_t pending_signal;
static void forward_signal(int number) {
    pending_signal = number;
    if (primary_pid > 0) kill((pid_t)primary_pid, number);
}

int main(int argc, char **argv) {
    if (argc < 10 || (strcmp(argv[1], "--development-only") && strcmp(argv[1], "--managed-session")) || strcmp(argv[8], "--")) {
        fputs("maintenance_es_helper: disabled\n", stderr); return 78;
    }
    /* socket, collector requirement, self requirement, resource, nonce, image alias, -- command */
    if (!token_ok(argv[5]) || !token_ok(argv[6]) || !token_ok(argv[7])) return 78;
    SecRequirementRef collector = requirement_file(argv[3]), self = requirement_file(argv[4]);
    if (!signed_code(NULL, self)) { fputs("signature_unverified\n", stderr); return 78; }
    int fd = socket_connect(argv[2]);
    audit_token_t peer;
    if (fd < 0 || !peer_token(fd, &peer) || peer.val[1] != 0 || !signed_code(&peer, collector)) {
        fputs("collector_unverified\n", stderr); return 78;
    }
    signal(SIGPIPE, SIG_IGN);
    char line[1024], parts[1][FIELD];
    if (!format(line, sizeof(line), "REGISTER %s %s %s\n", argv[5], argv[6], argv[7])) return 78;
    if (!write_all(fd, line) || read_line(fd, line, sizeof(line)) < 0 ||
        !fields(line, "ARM", parts, 1)) return 78;
    /* Exactly one ARM is read; never reconnect/retry a consumed execution permit. */
    signal(SIGTERM, forward_signal); signal(SIGINT, forward_signal);
    sigset_t blocked, previous;
    sigemptyset(&blocked); sigaddset(&blocked, SIGTERM); sigaddset(&blocked, SIGINT);
    if (sigprocmask(SIG_BLOCK, &blocked, &previous)) return 71;
    pid_t child = fork();
    if (child < 0) { write_all(fd, "SPAWN_FAILED\n"); return 71; }
    if (child == 0) { close(fd); signal(SIGTERM, SIG_DFL); signal(SIGINT, SIG_DFL); signal(SIGPIPE, SIG_DFL); sigprocmask(SIG_SETMASK, &previous, NULL); execvp(argv[9], &argv[9]); _exit(127); }
    primary_pid = child;
    if (pending_signal) kill(child, pending_signal);
    sigprocmask(SIG_SETMASK, &previous, NULL);
    if (format(line, sizeof(line), "START %d\n", child)) write_all(fd, line);
    int status;
    pid_t waited;
    do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
    if (waited != child) return 71;
    primary_pid = 0;
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    if (format(line, sizeof(line), "WAIT %d %d\n", child, code) && write_all(fd, line)) {
        /* Stay alive for audit-token signature validation until durable wait ACK or EOF. */
        (void)read_line(fd, line, sizeof(line));
    }
    /* IPC loss after launch never interrupts child or replaces its business result. */
    close(fd);
    return code;
}
