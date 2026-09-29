#!/usr/bin/env python3
import os, sys, time, gzip, signal, threading, queue
from datetime import datetime

LOG_DIR='/var/log/blocked_process_monitor'
SCAN_INTERVAL=5
ROTATE_SECONDS=2*60*60
HANG_THRESHOLD_SECONDS=10
TOP_N=15
running=True
log_queue=queue.Queue()
log_file=None
log_file_path=None
lock=threading.RLock()
cpu_prev={}; io_prev={}; d_since={}

def ts(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def read(path):
    try:
        with open(path,'r',errors='replace') as f: return f.read()
    except OSError: return None
def pids():
    try: return [int(x) for x in os.listdir('/proc') if x.isdigit()]
    except OSError: return []
def stat(pid):
    d=read(f'/proc/{pid}/stat')
    if not d: return None
    try:
        x=d[d.rfind(')')+2:].split(); return x[0],int(x[1]),int(x[11]),int(x[12])
    except Exception: return None
def name(pid):
    d=read(f'/proc/{pid}/comm'); return d.strip() if d else 'UNKNOWN'
def cmd(pid):
    try:
        with open(f'/proc/{pid}/cmdline','rb') as f: return f.read().replace(b'\0',b' ').decode(errors='replace').strip()
    except OSError: return ''
def io(pid):
    d=read(f'/proc/{pid}/io'); r={}
    if d:
        for l in d.splitlines():
            if ':' in l:
                k,v=l.split(':',1)
                if k.strip() in ('read_bytes','write_bytes'): 
                    try:r[k.strip()]=int(v)
                    except ValueError:pass
    return r
def wchan(pid):
    d=read(f'/proc/{pid}/wchan'); return d.strip() if d else 'UNKNOWN'
def uid(pid):
    d=read(f'/proc/{pid}/status')
    if d:
        for l in d.splitlines():
            if l.startswith('Uid:'):
                try:return int(l.split()[1])
                except:pass
    return -1
def fds(pid):
    out=[]
    try: entries=os.listdir(f'/proc/{pid}/fd')
    except OSError:return out
    for fd in entries:
        try:
            t=os.readlink(f'/proc/{pid}/fd/{fd}')
            if t.startswith('/dev/') or t.startswith('/') or t.startswith('socket:') or t.startswith('pipe:'): out.append(f'{fd}->{t}')
        except OSError: pass
    return out[:30]
def enqueue(s):
    try: log_queue.put(s)
    except: pass

def cpu_monitor():
    global cpu_prev
    while running:
        cur={}; rows=[]
        for p in pids():
            s=stat(p)
            if not s: continue
            state,pp,ut,st=s; total=ut+st; cur[p]=total
            if p in cpu_prev:
                pct=max(0,(total-cpu_prev[p])/max(1,SCAN_INTERVAL)/100)
                rows.append((pct,p,pp,state,name(p),cmd(p)))
        cpu_prev=cur; rows.sort(reverse=True)
        lines=[f'\n[{ts()}] TOP CPU PROCESSES','CPU%       PID       PPID      STATE  NAME                         CMD']
        for a,p,pp,st,n,c in rows[:TOP_N]: lines.append(f'{a:8.2f} {p:9} {pp:9} {st:>5}  {n[:28]:28} {c[:120]}')
        enqueue('\n'.join(lines)); time.sleep(SCAN_INTERVAL)

def memory_monitor():
    while running:
        rows=[]
        for p in pids():
            d=read(f'/proc/{p}/status'); rss=0
            if d:
                for l in d.splitlines():
                    if l.startswith('VmRSS:'):
                        try:rss=int(l.split()[1])
                        except:rss=0
                        break
            if rss:
                s=stat(p); rows.append((rss,p,s[0] if s else '?',name(p),cmd(p)))
        rows.sort(reverse=True)
        lines=[f'\n[{ts()}] TOP MEMORY PROCESSES','RSS_MB     PID       STATE  NAME                         CMD']
        for r,p,st,n,c in rows[:TOP_N]: lines.append(f'{r/1024:8.2f} {p:9} {st:>5}  {n[:28]:28} {c[:120]}')
        enqueue('\n'.join(lines)); time.sleep(SCAN_INTERVAL)

def io_monitor():
    global io_prev
    while running:
        cur={}; rows=[]
        for p in pids():
            d=io(p)
            if not d: continue
            r,w=d.get('read_bytes',0),d.get('write_bytes',0); cur[p]=(r,w)
            if p in io_prev:
                pr,pw=io_prev[p]; rr=max(0,r-pr)/max(1,SCAN_INTERVAL); wr=max(0,w-pw)/max(1,SCAN_INTERVAL)
                if rr+wr:
                    s=stat(p); rows.append((rr+wr,rr,wr,p,s[0] if s else '?',name(p),cmd(p)))
        io_prev=cur; rows.sort(reverse=True)
        lines=[f'\n[{ts()}] TOP I/O PROCESSES','TOTAL_MB/s  READ_MB/s  WRITE_MB/s  PID       STATE  NAME                         CMD']
        for total,r,w,p,st,n,c in rows[:TOP_N]: lines.append(f'{total/1048576:11.2f} {r/1048576:10.2f} {w/1048576:11.2f} {p:9} {st:>5}  {n[:28]:28} {c[:100]}')
        enqueue('\n'.join(lines)); time.sleep(SCAN_INTERVAL)

def blocked_monitor():
    global d_since
    while running:
        now=time.time(); active=set()
        for p in pids():
            s=stat(p)
            if not s or s[0]!='D': continue
            active.add(p); d_since.setdefault(p,now); dur=now-d_since[p]
            if dur>=HANG_THRESHOLD_SECONDS:
                x=io(p); lines=[f'\n[{ts()}] D-STATE / BLOCKED PROCESS',f'PID             : {p}',f'PPID            : {s[1]}',f'UID             : {uid(p)}',f'NAME            : {name(p)}',f'COMMAND         : {cmd(p)}',f'STATE           : D',f'BLOCKED_SECONDS : {dur:.1f}',f'WCHAN           : {wchan(p)}',f'READ_BYTES      : {x.get("read_bytes",0)}',f'WRITE_BYTES     : {x.get("write_bytes",0)}','OPEN_FILES/DEVICES:']
                lines += [f'  {z}' for z in fds(p)] or ['  <none/unavailable>']; enqueue('\n'.join(lines))
        d_since={p:t for p,t in d_since.items() if p in active}; time.sleep(SCAN_INTERVAL)

def system_monitor():
    while running:
        try:l1,l5,l15=os.getloadavg()
        except OSError:l1=l5=l15=0
        mem=read('/proc/meminfo') or ''; m={}
        for l in mem.splitlines():
            z=l.split();
            if len(z)>=2:
                try:m[z[0].rstrip(':')]=int(z[1])
                except:pass
        total=m.get('MemTotal',0); avail=m.get('MemAvailable',m.get('MemFree',0)); pct=(total-avail)*100/total if total else 0
        pc=tc=dc=0
        for p in pids():
            s=stat(p)
            if not s:continue
            pc+=1; dc+=s[0]=='D'; d=read(f'/proc/{p}/status') or ''
            for l in d.splitlines():
                if l.startswith('Threads:'):
                    try:tc+=int(l.split()[1])
                    except:pass
                    break
        enqueue(f'\n[{ts()}] SYSTEM SUMMARY\nLOAD_1M        : {l1:.2f}\nLOAD_5M        : {l5:.2f}\nLOAD_15M       : {l15:.2f}\nCPU_COUNT      : {os.cpu_count()}\nMEM_TOTAL_MB   : {total/1024:.2f}\nMEM_AVAILABLE_MB: {avail/1024:.2f}\nMEM_USED_PCT   : {pct:.2f}\nPROCESS_COUNT  : {pc}\nTHREAD_COUNT   : {tc}\nD_STATE_COUNT  : {dc}')
        time.sleep(SCAN_INTERVAL)

def open_log():
    global log_file,log_file_path
    with lock:
        os.makedirs(LOG_DIR,exist_ok=True); log_file_path=os.path.join(LOG_DIR,'system_monitor_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.log'); log_file=open(log_file_path,'a',buffering=1); log_file.write(f'===== STARTED {ts()} =====\n')
def close_log():
    global log_file
    with lock:
        if log_file:
            try:log_file.flush();log_file.close()
            except:pass
            log_file=None
def rotate():
    global log_file_path
    with lock:
        old=log_file_path; close_log()
        if old and os.path.exists(old):
            try:
                with open(old,'rb') as s,gzip.open(old+'.gz','wb') as d:
                    while True:
                        b=s.read(1048576)
                        if not b:break
                        d.write(b)
                os.remove(old)
            except Exception as e:sys.stderr.write(f'{ts()} compression failed: {e}\n')
        open_log()
def writer():
    while running or not log_queue.empty():
        try:m=log_queue.get(timeout=1)
        except queue.Empty:continue
        try:
            with lock:
                if log_file:log_file.write(m+'\n');log_file.flush()
        finally:log_queue.task_done()
def rotation():
    while running:
        time.sleep(1)
        if not running:break
        with lock:path=log_file_path
        try:
            if path and time.time()-os.path.getmtime(path)>=ROTATE_SECONDS:rotate()
        except OSError:pass
def stop(sig,frame):
    global running
    running=False
    enqueue(f'\n[{ts()}] Shutdown signal received.')

def main():
    global running
    if os.geteuid()!=0: print('WARNING: root is recommended for complete /proc access and log permissions.',file=sys.stderr)
    os.makedirs(LOG_DIR,exist_ok=True);open_log();signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    funcs=[cpu_monitor,memory_monitor,io_monitor,blocked_monitor,system_monitor,writer,rotation]
    threads=[threading.Thread(target=f,name=f.__name__,daemon=True) for f in funcs]
    for t in threads:t.start()
    enqueue(f'[{ts()}] Monitoring started. Log directory: {LOG_DIR}')
    try:
        while running:time.sleep(1)
    except KeyboardInterrupt:running=False
    for t in threads:
        if t.name!='writer':t.join(timeout=SCAN_INTERVAL+2)
    log_queue.join()
    for t in threads:t.join(timeout=3)
    close_log();print(f'Monitoring stopped. Logs are in {LOG_DIR}')

if __name__=='__main__':main()
