#!/usr/bin/env bash
# Download historical play-by-play (shufinskiy/nba_data, cdn.nba.com format) and build the
# replay file baked into the image. Seasons are named by start year: 2024 = 2024-25.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw data/replay
for y in ${SEASONS:-2020 2021 2022 2023 2024}; do
  [ -f "data/raw/cdnnba_$y.csv" ] && continue
  curl -sSfL "https://raw.githubusercontent.com/shufinskiy/nba_data/main/datasets/cdnnba_$y.tar.xz" | tar -xJ -C data/raw
done
uv run python -c "
import pandas as pd
from ingest.replayer import COLS
pd.read_csv('data/raw/cdnnba_2024.csv', usecols=COLS, low_memory=False).to_parquet('data/replay/season_2024.parquet', index=False)"
ls -la data/replay
