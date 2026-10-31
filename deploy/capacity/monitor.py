"""Read-only cgroup-v2/host sampler; no Docker socket or process environments."""
import json,time
from pathlib import Path

ROOT=Path('/measure')


def pairs(path):
    return {key.rstrip(':'):int(value.split()[0]) for key,value in (line.split(maxsplit=1) for line in path.read_text().splitlines())}


with (ROOT/'samples.jsonl').open('a', buffering=1) as output:
    while not (ROOT/'stop').exists():
        memory=pairs(Path('/host-proc/meminfo'))
        vm=pairs(Path('/host-proc/vmstat'))
        services={}
        # A host shared directory can briefly lag behind an atomic rename.
        try:mapping=json.loads((ROOT/'services.json').read_text())
        except (FileNotFoundError,json.JSONDecodeError):time.sleep(.25);continue
        for identity,service in mapping.items():
            try:
                relative=Path('/host-proc',str(service['pid']),'cgroup').read_text().strip().split(':',2)[2].lstrip('/')
                if not relative.endswith(identity):continue
                group=Path('/cgroup')/relative
                stats=pairs(group/'memory.stat')
                current=int((group/'memory.current').read_text())
                services[service['name']]={'id':identity,'memory':current,'working_set':max(0,current-stats['inactive_file']),
                    'peak':int((group/'memory.peak').read_text()),'events':pairs(group/'memory.events'),
                    'cpu':pairs(group/'cpu.stat')}
            except FileNotFoundError:pass
        root_cpu=Path('/cgroup')/(ROOT/'parent').read_text().strip()/'cpu.stat'
        row={'at':time.time(),'phase':(ROOT/'phase').read_text().strip(),
             'host':{'total':memory['MemTotal']*1024,'available':memory['MemAvailable']*1024,
                     'used':(memory['MemTotal']-memory['MemAvailable'])*1024,
                     'swap_used':(memory['SwapTotal']-memory['SwapFree'])*1024,'oom_kill':vm['oom_kill']},
             'services':services,'parent_cpu':pairs(root_cpu) if root_cpu.exists() else {}}
        output.write(json.dumps(row,separators=(',',':'))+'\n')
        if not (ROOT/'ready').exists():(ROOT/'ready').touch()
        time.sleep(.25)
