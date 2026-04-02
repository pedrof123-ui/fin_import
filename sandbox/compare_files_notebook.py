"""Notebook-ready script to compare two text files row by row.

Copy this code into a Jupyter notebook cell.
"""

from pathlib import Path

# File paths
file1_path = Path("/home/pedro/projects/fin_import2/step35_response_dicts.txt")
file2_path = Path("/home/pedro/projects/fin_import2/qwen_response_dicts.txt")

# Read both files
with file1_path.open('r', encoding='utf-8') as f:
    lines1 = [line.rstrip('\n\r') for line in f]

with file2_path.open('r', encoding='utf-8') as f:
    lines2 = [line.rstrip('\n\r') for line in f]

# Print summary
print(f"File 1: {file1_path.name} ({len(lines1)} lines)")
print(f"File 2: {file2_path.name} ({len(lines2)} lines)")
print("-" * 80)

# Find and report differences
max_lines = max(len(lines1), len(lines2))
differences = []

for line_num in range(max_lines):
    line1 = lines1[line_num] if line_num < len(lines1) else None
    line2 = lines2[line_num] if line_num < len(lines2) else None
    
    if line1 != line2:
        differences.append((line_num + 1, line1 or "[MISSING]", line2 or "[MISSING]"))

# Print results
if not differences:
    print("✓ Files are identical!")
else:
    print(f"Found {len(differences)} difference(s):\n")
    for line_num, content1, content2 in differences:
        print(f"Line {line_num}:")
        print(f"  File 1: {content1}")
        print(f"  File 2: {content2}")
        print()
