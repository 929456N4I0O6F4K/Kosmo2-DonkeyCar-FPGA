/* One-shot LAN transfer helper. UART must verify SHA-256 before using the file.
 * Usage: receive_file PORT EXPECTED_BYTES NEW_FILE
 * Refuses existing paths, limits byte count and lifetime, accepts one client.
 */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    char buffer[32768], *end;
    long port;
    unsigned long expected, received = 0;
    int listener = -1, client = -1, file = -1, result = 1;
    ssize_t count;
    struct sockaddr_in address = {0};
    if (argc != 4) return 2;
    port = strtol(argv[1], &end, 10);
    if (*end || port < 1024 || port > 65535) return 2;
    expected = strtoul(argv[2], &end, 10);
    if (*end || !expected || expected > 64UL * 1024 * 1024) return 2;
    alarm(180);
    file = open(argv[3], O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (file < 0) { perror("open output"); return 1; }
    listener = socket(AF_INET, SOCK_STREAM, 0);
    if (listener < 0) goto done;
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons((unsigned short) port);
    if (bind(listener, (struct sockaddr *) &address, sizeof(address)) < 0 || listen(listener, 1) < 0)
        goto done;
    puts("READY"); fflush(stdout);
    client = accept(listener, NULL, NULL);
    if (client < 0) goto done;
    close(listener); listener = -1;
    while ((count = read(client, buffer, sizeof(buffer))) != 0) {
        ssize_t offset = 0;
        if (count < 0) { if (errno == EINTR) continue; goto done; }
        if (received + (unsigned long) count > expected) goto done;
        while (offset < count) {
            ssize_t written = write(file, buffer + offset, (size_t) (count - offset));
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) goto done;
            offset += written;
        }
        received += (unsigned long) count;
    }
    if (received != expected || fsync(file) < 0) goto done;
    printf("RECEIVED %lu bytes; verify SHA256 via UART\n", received);
    result = 0;
done:
    if (result) fprintf(stderr, "Transfer failed: received %lu of %lu bytes\n", received, expected);
    if (client >= 0) close(client);
    if (listener >= 0) close(listener);
    if (file >= 0) close(file);
    if (result) unlink(argv[3]);
    return result;
}
