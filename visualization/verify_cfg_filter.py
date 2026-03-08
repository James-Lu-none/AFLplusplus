import os
import sys
from core.cfg_processor import load_cfg_with_graphviz

# Create a dummy cfg_edges.txt if it doesn't exist for testing
test_file = "test_cfg_edges.txt"
with open(test_file, "w") as f:
    f.write("%A, %B, [label1]\n")
    f.write("%A, %C, [label2]\n")
    f.write("%B, %D, [label3]\n")
    f.write("%C, %D, [label4]\n")
    f.write("%D, %E, [label5]\n")
    f.write("%D, %F, [label6]\n")

# Node degrees in this graph:
# A: 2 (out: B, C)
# B: 2 (in: A, out: D)
# C: 2 (in: A, out: D)
# D: 4 (in: B, C, out: E, F)
# E: 1 (in: D)
# F: 1 (in: D)

# Top node is D (degree 4).
# If we filter N=1, D should be removed.

print("--- Testing N=0 ---")
elements_n0 = load_cfg_with_graphviz(test_file, top_n=0)
nodes_n0 = [e['data']['id'] for e in elements_n0 if 'id' in e['data']]
print(f"Nodes with N=0: {nodes_n0}")

print("\n--- Testing N=1 ---")
elements_n1 = load_cfg_with_graphviz(test_file, top_n=1)
nodes_n1 = [e['data']['id'] for e in elements_n1 if 'id' in e['data']]
print(f"Nodes with N=1: {nodes_n1}")

if 'D' not in nodes_n1 and 'D' in nodes_n0:
    print("\nSUCCESS: Top node D was removed.")
else:
    print("\nFAILURE: Top node D was not removed correctly.")

# Cleanup
if os.path.exists(test_file):
    os.remove(test_file)
