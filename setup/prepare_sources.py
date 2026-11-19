import csv
import gzip
from pathlib import Path

# Paths
RAW_DATA_PATH = Path("../paysim.csv")  # Path where raw Kaggle CSV is kept outside repo
OUTPUT_PATH = Path("api/data/paysim_api_v1.csv.gz")

def prepare_paysim_sample():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(f"Raw PaySim dataset not found at {RAW_DATA_PATH}. Please download it from Kaggle and place it outside the repository.")

    print(f"Reading first 100,000 rows from {RAW_DATA_PATH}...")
    
    rows = []
    with open(RAW_DATA_PATH, mode="r", encoding="utf-8", newline="") as f_in:
        reader = csv.reader(f_in)
        header = next(reader)
        rows.append(header)
        
        for i, row in enumerate(reader):
            if i >= 100000:
                break
            rows.append(row)

    print(f"Writing deterministic gzipped sample to {OUTPUT_PATH}...")
    # mtime=0 ensures deterministic gzip file creation timestamp hashes
    with gzip.open(OUTPUT_PATH, mode="wt", encoding="utf-8", newline="", mtime=0) as f_out:
        writer = csv.writer(f_out)
        writer.writerows(rows)

    print("Successfully generated paysim_api_v1.csv.gz!")

if __name__ == "__main__":
    prepare_paysim_sample()
