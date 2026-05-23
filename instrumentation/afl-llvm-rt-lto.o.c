/*
   american fuzzy lop++ - LLVM instrumentation bootstrap
   -----------------------------------------------------

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at:

     https://www.apache.org/licenses/LICENSE-2.0

*/

#include <stdio.h>
#include <stdlib.h>

// to prevent the function from being removed
unsigned char __afl_lto_mode = 0;

void __afl_dgf_target_hit(void);

__attribute__((constructor(0))) void __afl_auto_init_globals(void) {

  if (getenv("AFL_DEBUG")) fprintf(stderr, "[__afl_auto_init_globals]\n");
  __afl_lto_mode = 1;

  // Volatile reference to prevent __afl_dgf_target_hit from being optimized out by LTO
  void (*volatile dummy)(void) = __afl_dgf_target_hit;
  (void)dummy;

}

__attribute__((used)) void __afl_dgf_target_hit(void) {
  // Check if target reached file already exists to avoid redundant writes
  FILE *check = fopen("dgf_target_reached.txt", "r");
  if (check) {
    fclose(check);
    return;
  }
  FILE *f = fopen("dgf_target_reached.txt", "w");
  if (f) {
    fprintf(f, "Target reached!\n");
    fclose(f);
  }
  fprintf(stderr, "\n[DGF] Target basic block successfully reached! Status saved to dgf_target_reached.txt\n");
}

