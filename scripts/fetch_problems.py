#!/usr/bin/env python3
"""Download a balanced, cached sample using the site's 100-task page and 20s delay."""
import argparse,fcntl,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from core.problems_ru import Fetcher,collect,save_json

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=500)
    parser.add_argument('--max-pages',type=int,default=35)
    parser.add_argument('--cache-dir',type=Path,default=ROOT/'.local/problems-ru-cache')
    parser.add_argument('--output',type=Path,default=ROOT/'data/problems_ru_sample.json')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    if not 1<=args.limit<=10000 or not 1<=args.max_pages<=200:parser.error('Недопустимый размер выборки')
    data=json.loads((ROOT/'data/problems_topics.json').read_text())
    subjects={row['source_id']:row['name'] for row in data['source_nodes'] if row['parent_source_id']=='1302'}
    args.cache_dir.mkdir(parents=True,exist_ok=True)
    with (args.cache_dir/'fetch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        result=collect(Fetcher(args.cache_dir,args.offline),subjects,args.limit,args.max_pages)
        save_json(args.output,result)
    print(f'Сохранено задач: {len(result["problems"])}; файл: {args.output}',flush=True)

if __name__=='__main__':main()
