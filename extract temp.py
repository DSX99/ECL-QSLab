import pandas as pd
from pathlib import Path

base_path = Path("./2026-04-13")
csv_path = 'manual_file_name.csv'

df = pd.read_csv(csv_path, header=0, skiprows=[1, 2])

df.columns = df.columns.str.strip()
df = df[['Date/Time', '50 mK FAA Temperature']]

df['Date/Time'] = pd.to_datetime(df['Date/Time'], format='%m/%d/%Y %H:%M:%S', errors='coerce')
df = df.dropna(subset=['Date/Time'])

# df = df.sort_values('Date/Time').reset_index(drop=True)

folders = [f for f in base_path.iterdir() if f.is_dir()]

print(f"Found {len(folders)} folders to process...")

for folder in folders:
    try:
        folder_time = pd.to_datetime(folder.name, format='%Y-%m-%d-%H-%M-%S')
        search_df = pd.DataFrame({'Date/Time': [folder_time]})

        result = pd.merge_asof(search_df, df, on='Date/Time', direction='nearest')
        
        temp_val = result['50 mK FAA Temperature'].values[0]
        
        if pd.isna(temp_val):
            print(f"Skipping {folder.name}: No temperature data found.")
            continue

        new_name = f"{folder.name}_{temp_val:.4f}mK"
        new_path = folder.parent / new_name
        folder.rename(new_path)
        
    except Exception as e:
        print(f"Error processing {folder.name}: {e}")