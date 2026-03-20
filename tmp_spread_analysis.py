import pandas as pd
from pathlib import Path

path = Path('d:/lkh/Cornell/Gemini Trading Contest/mm_code/input/gemini_24h_analysis.csv')
usecols = ['best_bid', 'best_ask']
df = pd.read_csv(path, usecols=usecols).dropna()
mid = (df['best_bid'] + df['best_ask']) / 2
spread = df['best_ask'] - df['best_bid']
half_bps = (spread / 2) / mid * 1e4
print('rows:', len(df))
print('median half spread bps:', half_bps.median())
print('75th pct half spread bps:', half_bps.quantile(0.75))
print('90th pct half spread bps:', half_bps.quantile(0.90))
print('max half spread bps:', half_bps.max())
print('mean half spread bps:', half_bps.mean())
