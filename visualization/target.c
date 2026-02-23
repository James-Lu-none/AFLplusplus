#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void process_data(char *buf, size_t len)
{
    if (len >= 4)
    {
        if (buf[0] == 'F' && buf[1] == 'L' && buf[2] == 'A' && buf[3] == 'M')
        {
            printf("Found the magic header!\n");
            if (len > 10 && len < 20)
            {
                char small_stack[8];
                printf("Triggering overflow...\n");
                memcpy(small_stack, buf, len);
            }
            if (buf[4] == '!')
            {
                printf("Target hit!\n");
                char *ptr = NULL;
                *ptr = 'X';
            }
        }
    }
}

int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        printf("Usage: %s <filename>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f)
    {
        perror("fopen");
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *buf = malloc(len);
    if (!buf)
        return 1;

    fread(buf, 1, len, f);
    fclose(f);

    process_data(buf, len);

    free(buf);
    return 0;
}