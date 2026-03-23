import csv
with open("security_results.csv", "r") as f:
    reader = csv.reader(f)
    with open("targets.csv", "w") as out:
        for row in reader:
            if len(row) >= 6:
                path = row[4].lstrip("/")
                lineStart = row[5]
                lineEnd = row[7]
                out.write(f"{path},{lineStart},{lineEnd}\n")