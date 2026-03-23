#!/bin/bash

SESSION="fuzz_session"

INPUT_DIR="./in"    
OUTPUT_DIR="./out"      

codeql database create ./codeqldb --language=cpp --command="afl-clang-lto target.c -o target_normal"
codeql database analyze ./codeqldb \
    codeql/cpp-queries:codeql-suites/cpp-security-and-quality.qls \
    --format=csv \
    --output=security_results.csv
python3 extract_targets.py

tmux kill-session -t $SESSION 2>/dev/null
rm -rf $OUTPUT_DIR
rm cfg_edges.txt
mkdir -p $INPUT_DIR
mkdir -p $OUTPUT_DIR
echo "init_seed" > $INPUT_DIR/seed.txt

afl-clang-lto target.c -o target_normal

tmux new-session -d -s $SESSION -n "main" "afl-fuzz -i $INPUT_DIR -o $OUTPUT_DIR -M main -- ./target_normal @@"
tmux new-window -t $SESSION -n "reader" "python3 app.py"

echo "Fuzzing session '$SESSION' started!"
echo "Use 'tmux attach -t $SESSION' to see progress."