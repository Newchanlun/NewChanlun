/* Isolated kernel IPC test, not ES coverage or approved-signature acceptance. */
#include "common.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>
int main(void) {
    char directory[] = "/tmp/nc-es-peer.XXXXXX";
    assert(mkdtemp(directory));
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    snprintf(address.sun_path, sizeof(address.sun_path), "%s/socket", directory);
    int server = socket(AF_UNIX, SOCK_STREAM, 0);
    assert(server >= 0 && bind(server, (struct sockaddr *)&address, sizeof(address)) == 0 && listen(server, 1) == 0);
    pid_t child = fork(); assert(child >= 0);
    if (child == 0) {
        close(server);
        int connection = socket_connect(address.sun_path);
        audit_token_t peer;
        if (connection < 0 || !peer_token(connection, &peer) || peer.val[5] != (uint32_t)getppid()) _exit(1);
        if (!write_all(connection, "ready\n")) _exit(2);
        char line[32]; if (read_line(connection, line, sizeof(line)) < 0) _exit(3);
        close(connection); _exit(0);
    }
    int connection = accept(server, NULL, NULL); assert(connection >= 0);
    char line[32]; assert(read_line(connection, line, sizeof(line)) == 5);
    audit_token_t peer; assert(peer_token(connection, &peer));
    assert(peer.val[5] == (uint32_t)child && peer.val[1] == (uint32_t)geteuid() && peer.val[7] > 0);
    assert(write_all(connection, "done\n"));
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    close(connection); close(server); assert(unlink(address.sun_path) == 0 && rmdir(directory) == 0);
    puts("LOCAL_PEERTOKEN: exact isolated child and server identities passed; no ES/signature acceptance tested");
    return 0;
}
