#include <stdio.h>
#include <stdlib.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/mman.h>

// to prevent the function from being removed
unsigned char __afl_lto_mode = 0;

static unsigned long long __afl_dgf_start_time = 0;

#define MAX_DGF_BLOCKS 1048576
static unsigned char __afl_dgf_blocks_hit[MAX_DGF_BLOCKS] = {0};
static unsigned char *__afl_dgf_shared_hit_map = NULL;

static unsigned long long get_current_time_ms(void) {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (unsigned long long)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

void __afl_dgf_target_hit(void);
void __afl_dgf_block_hit(unsigned int type, unsigned int id);

__attribute__((constructor(0))) void __afl_auto_init_globals(void) {

  if (getenv("AFL_DEBUG")) fprintf(stderr, "[__afl_auto_init_globals]\n");
  __afl_lto_mode = 1;

  __afl_dgf_start_time = get_current_time_ms();

  // Create/open shared memory backing file and map it
  int fd = open("dgf_shm.bin", O_RDWR | O_CREAT, 0644);
  if (fd >= 0) {
    struct stat st;
    if (fstat(fd, &st) == 0 && st.st_size < MAX_DGF_BLOCKS) {
      if (ftruncate(fd, MAX_DGF_BLOCKS) != 0) {
        // Handle error if truncate fails
      }
    }
    __afl_dgf_shared_hit_map = (unsigned char *)mmap(NULL, MAX_DGF_BLOCKS, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (__afl_dgf_shared_hit_map == MAP_FAILED) {
      __afl_dgf_shared_hit_map = NULL;
    }
  }

  // Initialize output file for block hit log if not already created
  FILE *check = fopen("dgf_blocks_hit.txt", "r");
  if (!check) {
    FILE *f = fopen("dgf_blocks_hit.txt", "w");
    if (f) {
      fprintf(f, "Type,ID,ElapsedMS\n");
      fclose(f);
    }
  } else {
    fclose(check);
  }

  // Volatile references to prevent hit handlers from being optimized out by LTO
  void (*volatile dummy1)(void) = __afl_dgf_target_hit;
  void (*volatile dummy2)(unsigned int, unsigned int) = __afl_dgf_block_hit;
  (void)dummy1;
  (void)dummy2;

}

__attribute__((used)) void __afl_dgf_target_hit(void) {
  // Check if target reached file already exists to avoid redundant writes
  FILE *check = fopen("dgf_target_reached.txt", "r");
  if (check) {
    fclose(check);
    return;
  }

  unsigned long long hit_time_ms = get_current_time_ms();
  unsigned long long elapsed_ms = hit_time_ms - __afl_dgf_start_time;

  time_t start_sec = (time_t)(__afl_dgf_start_time / 1000);
  time_t hit_sec = (time_t)(hit_time_ms / 1000);

  char start_time_str[64];
  char hit_time_str[64];

  struct tm *tm_start = localtime(&start_sec);
  if (tm_start) {
    strftime(start_time_str, sizeof(start_time_str), "%Y-%m-%d %H:%M:%S", tm_start);
  } else {
    snprintf(start_time_str, sizeof(start_time_str), "unknown");
  }

  struct tm *tm_hit = localtime(&hit_sec);
  if (tm_hit) {
    strftime(hit_time_str, sizeof(hit_time_str), "%Y-%m-%d %H:%M:%S", tm_hit);
  } else {
    snprintf(hit_time_str, sizeof(hit_time_str), "unknown");
  }

  FILE *f = fopen("dgf_target_reached.txt", "w");
  if (f) {
    fprintf(f, "Target reached!\n");
    fprintf(f, "Start Time: %s (%llu ms)\n", start_time_str, __afl_dgf_start_time);
    fprintf(f, "Hit Time:   %s (%llu ms)\n", hit_time_str, hit_time_ms);
    fprintf(f, "Elapsed:    %.3f seconds (%llu ms)\n", (double)elapsed_ms / 1000.0, elapsed_ms);
    fclose(f);
  }
  fprintf(stderr, "\n[DGF] Target basic block successfully reached!\n");
  fprintf(stderr, "[DGF] Start Time: %s\n", start_time_str);
  fprintf(stderr, "[DGF] Hit Time:   %s\n", hit_time_str);
  fprintf(stderr, "[DGF] Elapsed:    %.3f seconds\n", (double)elapsed_ms / 1000.0);
}

__attribute__((used)) void __afl_dgf_block_hit(unsigned int type, unsigned int id) {
  if (id >= MAX_DGF_BLOCKS) return;
  if (__afl_dgf_blocks_hit[id]) return;

  if (__afl_dgf_shared_hit_map) {
    if (__afl_dgf_shared_hit_map[id]) {
      __afl_dgf_blocks_hit[id] = 1;
      return;
    }

    // Atomically check and set hit map using compare-and-swap
    if (__sync_bool_compare_and_swap(&__afl_dgf_shared_hit_map[id], 0, 1)) {
      __afl_dgf_blocks_hit[id] = 1;

      unsigned long long hit_time_ms = get_current_time_ms();
      unsigned long long elapsed_ms = hit_time_ms - __afl_dgf_start_time;

      FILE *f = fopen("dgf_blocks_hit.txt", "a");
      if (f) {
        fprintf(f, "%u,%u,%llu\n", type, id, elapsed_ms);
        fclose(f);
      }
      if (getenv("AFL_DEBUG")) {
        fprintf(stderr, "[DGF] Block hit: Type=%u, ID=%u, Elapsed=%llu ms\n", type, id, elapsed_ms);
      }
    } else {
      __afl_dgf_blocks_hit[id] = 1;
    }
  }
}
