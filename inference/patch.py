import os

file_path = "inference/processors/security.py"

with open(file_path, "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "original = original_batch[i]" in line:
        # Get indentation
        indent = line[:line.find("original")]
        new_lines.append(f"{indent}original = frame\n")
        print("✅ Patched line: original = frame")
    else:
        new_lines.append(line)

with open(file_path, "w") as f:
    f.writelines(new_lines)
