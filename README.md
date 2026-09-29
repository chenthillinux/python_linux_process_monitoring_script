# System Process Monitor

A lightweight, multi-threaded Linux system performance and
blocked-process monitoring utility written in Python 3.

The script is designed for troubleshooting situations where a Linux
server becomes slow, unresponsive, or experiences high load,
process/thread growth, high CPU usage, high memory consumption, heavy
process-level I/O, or processes stuck in the `D` (uninterruptible sleep)
state.

It uses the Linux `/proc` filesystem and standard Python libraries only.
No third-party Python packages are required.

------------------------------------------------------------------------

## Features

The monitor continuously collects:

-   System load averages
-   CPU count
-   Total and available memory
-   Memory utilization percentage
-   Total process count
-   Total thread count
-   Number of processes in `D` state
-   Top CPU-consuming processes
-   Top memory-consuming processes
-   Top process-level I/O activity
-   Processes stuck in `D` state
-   Duration for which a process remains in `D` state
-   Process wait channel (`WCHAN`)
-   Process command line
-   Parent PID (`PPID`)
-   User ID (`UID`)
-   Process read/write byte counters
-   Open files and device references for blocked processes
-   Timestamped monitoring information
-   Automatic log rotation every 2 hours
-   Gzip compression of completed log files
-   Concurrent collection using multiple Python threads

------------------------------------------------------------------------

## Why This Script Is Useful

When a Linux server is slow, the immediate challenge is identifying
whether the problem is related to:

1.  CPU pressure
2.  Memory pressure
3.  Excessive process creation
4.  Excessive thread creation
5.  Heavy process-level disk I/O
6.  Processes waiting for I/O
7.  Processes stuck in kernel wait states
8.  A combination of the above

The script collects these indicators continuously so that the data can
be reviewed after the incident.

For example, a performance incident may show:

``` text
High LOAD
   |
   +-- High CPU processes?
   |
   +-- High memory processes?
   |
   +-- High process/thread count?
   |
   +-- High I/O processes?
   |
   +-- D-state processes?
          |
          +-- WCHAN
          +-- Read/Write counters
          +-- Open files/devices
```

This makes the collected logs useful for incident investigation and RCA.

------------------------------------------------------------------------

# Architecture

The script uses separate monitoring threads.

``` text
                    +--------------------------+
                    | system_process_monitor   |
                    +------------+-------------+
                                 |
             +-------------------+-------------------+
             |                   |                   |
       CPU Monitor         Memory Monitor        I/O Monitor
             |                   |                   |
             +-------------------+-------------------+
                                 |
                       Blocked Process Monitor
                                 |
                       System Monitor
                                 |
             +-------------------+-------------------+
             |                                       |
        Log Queue                              Rotation Thread
             |
        Log Writer
             |
       Current .log file
             |
       Every 2 hours
             |
          gzip
             |
      .log.gz archive
```

Each monitoring function runs independently.

The monitoring threads place their output into a shared `queue.Queue`.

Only the log writer thread writes monitoring messages to the active log
file.

This prevents multiple monitoring threads from directly writing to the
same file at the same time.

------------------------------------------------------------------------

# Monitoring Threads

The script starts seven threads:

  -----------------------------------------------------------------------
  Thread                              Purpose
  ----------------------------------- -----------------------------------
  `cpu_monitor`                       Finds top CPU-consuming processes

  `memory_monitor`                    Finds top memory-consuming
                                      processes

  `io_monitor`                        Finds top process-level I/O
                                      activity

  `blocked_monitor`                   Detects processes in `D` state

  `system_monitor`                    Collects system-level load, memory,
                                      process and thread information

  `writer`                            Writes collected messages to the
                                      log file

  `rotation`                          Rotates and compresses logs every 2
                                      hours
  -----------------------------------------------------------------------

The monitoring interval is:

``` python
SCAN_INTERVAL = 5
```

Therefore, each monitoring thread normally performs its collection
approximately every 5 seconds.

------------------------------------------------------------------------

# 1. CPU Monitoring

The CPU monitoring thread reads process information from:

``` text
/proc/<PID>/stat
```

It collects:

-   PID
-   PPID
-   Process state
-   Process name
-   Command line
-   CPU time counters

The script keeps the previous CPU counters and calculates a CPU activity
rate between scans.

The top 15 processes are written to the log.

The number can be changed using:

``` python
TOP_N = 15
```

## Example

``` text
[2026-09-24 06:40:05] TOP CPU PROCESSES
CPU%       PID       PPID      STATE  NAME                         CMD
    25.40      4211      1002      S  java                         java -jar application.jar
    18.20      9821      1002      R  worker                       /opt/app/worker
```

This is useful for identifying processes that are consuming significant
CPU during a performance incident.

------------------------------------------------------------------------

# 2. Memory Monitoring

The memory monitor reads:

``` text
/proc/<PID>/status
```

It extracts:

``` text
VmRSS
```

`VmRSS` represents the resident memory currently associated with the
process.

The script sorts processes by RSS and records the top 15.

## Example

``` text
[2026-09-24 06:40:05] TOP MEMORY PROCESSES
RSS_MB     PID       STATE  NAME                         CMD
  4096.25      4211      S  java                         java -jar application.jar
  2048.50      9821      S  worker                       /opt/app/worker
```

This can help identify processes contributing to memory pressure.

------------------------------------------------------------------------

# 3. I/O Monitoring

The I/O monitor reads:

``` text
/proc/<PID>/io
```

It uses:

``` text
read_bytes
write_bytes
```

The script stores the previous values and calculates the change between
monitoring cycles.

It reports:

-   Total I/O MB/s
-   Read MB/s
-   Write MB/s
-   PID
-   Process state
-   Process name
-   Command line

## Example

``` text
[2026-09-24 06:40:05] TOP I/O PROCESSES
TOTAL_MB/s  READ_MB/s  WRITE_MB/s  PID       STATE  NAME                         CMD
      80.20       75.10        5.10      4211      D  java                         java -jar application.jar
      42.50       10.20       32.30      9821      S  worker                       /opt/app/worker
```

This helps answer questions such as:

-   Which process is generating heavy reads?
-   Which process is generating heavy writes?
-   Is a process currently performing significant I/O?
-   Is a process generating I/O while also being in `D` state?

------------------------------------------------------------------------

# 4. D-State / Blocked Process Monitoring

One of the main purposes of this script is identifying Linux processes
in:

``` text
D
```

state.

`D` represents uninterruptible sleep. A process in this state is
typically waiting for a kernel operation to complete, commonly involving
I/O or another kernel resource.

The script tracks how long a PID remains in `D` state.

The configured threshold is:

``` python
HANG_THRESHOLD_SECONDS = 10
```

A process that remains in `D` state for at least 10 seconds is logged.

## Information collected

For each qualifying process:

-   PID
-   PPID
-   UID
-   Process name
-   Command line
-   State
-   Duration in D state
-   WCHAN
-   Read bytes
-   Write bytes
-   Open files/devices

## Example

``` text
[2026-09-24 06:40:05] D-STATE / BLOCKED PROCESS
PID             : 4211
PPID            : 1002
UID             : 0
NAME            : java
COMMAND         : java -jar application.jar
STATE           : D
BLOCKED_SECONDS : 25.0
WCHAN           : io_schedule
READ_BYTES      : 109283840
WRITE_BYTES     : 5242880
OPEN_FILES/DEVICES:
  3->/dev/mapper/vg-lv_data
  4->/var/log/application.log
```

This information can be particularly useful when investigating:

-   Storage latency
-   Filesystem problems
-   Device-mapper/LVM waits
-   Network filesystem waits
-   Application processes waiting for I/O
-   Large numbers of blocked processes

The script reports the observed state and counters. It does not itself
determine the root cause of the kernel wait.

------------------------------------------------------------------------

# 5. System Monitoring

The system monitor collects system-level information using `/proc` and
standard Python system interfaces.

It records:

-   1-minute load average
-   5-minute load average
-   15-minute load average
-   CPU count
-   Total memory
-   Available memory
-   Memory utilization percentage
-   Process count
-   Thread count
-   D-state process count

## Example

``` text
[2026-09-24 06:40:05] SYSTEM SUMMARY
LOAD_1M        : 2498.89
LOAD_5M        : 1768.52
LOAD_15M       : 883.60
CPU_COUNT      : 32
MEM_TOTAL_MB   : 128000.00
MEM_AVAILABLE_MB: 42000.00
MEM_USED_PCT   : 67.19
PROCESS_COUNT  : 15225
THREAD_COUNT   : 18140
D_STATE_COUNT  : 325
```

This provides the high-level system picture that can be correlated with
the process-level information.

------------------------------------------------------------------------

# 6. Process and Thread Collection

The script counts both:

``` text
PROCESS_COUNT
THREAD_COUNT
```

The process count is obtained by scanning numeric directories under:

``` text
/proc
```

For each process, the script reads:

``` text
/proc/<PID>/status
```

and extracts:

``` text
Threads:
```

The total is then accumulated across processes.

## Why thread count matters

A server can have a relatively normal process count while still
experiencing abnormal thread growth.

For example:

``` text
PROCESS_COUNT : 3000
THREAD_COUNT  : 15000
```

may indicate that applications are creating large numbers of threads.

The script does not attempt to diagnose why the threads were created. It
provides the thread population so that it can be correlated with
application behavior and other system metrics.

------------------------------------------------------------------------

# 7. Log Collection

All monitoring threads send their output to:

``` python
log_queue = queue.Queue()
```

The monitoring threads do not directly write to the log file.

Instead:

``` text
Monitoring Thread
       |
       v
   log_queue
       |
       v
   writer thread
       |
       v
   log file
```

This provides a single logging path.

The default log directory is:

``` text
/var/log/blocked_process_monitor
```

------------------------------------------------------------------------

# Log File Naming

The active log file is created using:

``` text
system_monitor_YYYYMMDD_HHMMSS.log
```

Example:

``` text
system_monitor_20260924_063000.log
```

After rotation and compression:

``` text
system_monitor_20260924_063000.log.gz
```

------------------------------------------------------------------------

# Log Rotation

The script automatically rotates the active log every:

``` python
ROTATE_SECONDS = 2 * 60 * 60
```

which is:

``` text
2 hours
```

The rotation sequence is:

``` text
Current log
    |
    v
Close log
    |
    v
Compress using gzip
    |
    v
Delete uncompressed rotated file
    |
    v
Create new .log file
```

For example:

``` text
system_monitor_20260924_000000.log.gz
system_monitor_20260924_020000.log.gz
system_monitor_20260924_040000.log
```

The current log remains uncompressed until the next rotation.

------------------------------------------------------------------------

# Log Compression

Python's standard `gzip` module is used.

No external compression utility is required by the script.

Compressed files can be viewed using:

``` bash
zcat system_monitor_*.log.gz
```

or searched using:

``` bash
zgrep -Ei "D-STATE|BLOCKED|WCHAN" system_monitor_*.log.gz
```

------------------------------------------------------------------------

# Data Sources

The script relies primarily on Linux `/proc`.

Important sources include:

``` text
/proc/<PID>/stat
/proc/<PID>/status
/proc/<PID>/io
/proc/<PID>/comm
/proc/<PID>/cmdline
/proc/<PID>/wchan
/proc/<PID>/fd/
/proc/meminfo
```

This means the script is lightweight and does not require external
monitoring agents or Python packages.

------------------------------------------------------------------------

# Installation

## Requirements

-   Linux operating system
-   Python 3
-   `/proc` filesystem
-   Permission to read process information
-   Permission to write to `/var/log/blocked_process_monitor`

Running as `root` is recommended when complete process visibility is
required.

Check Python:

``` bash
python3 --version
```

------------------------------------------------------------------------

## Install the Script

Copy the script:

``` bash
sudo cp system_process_monitor.py /usr/local/bin/system_process_monitor.py
```

Set permissions:

``` bash
sudo chmod 750 /usr/local/bin/system_process_monitor.py
```

Create the log directory:

``` bash
sudo mkdir -p /var/log/blocked_process_monitor
```

Optional ownership configuration:

``` bash
sudo chown root:root /usr/local/bin/system_process_monitor.py
sudo chown root:root /var/log/blocked_process_monitor
```

------------------------------------------------------------------------

# Starting the Monitor

## Option 1: Foreground

Run:

``` bash
sudo /usr/local/bin/system_process_monitor.py
```

The monitor stays attached to the terminal.

You will see:

``` text
Monitoring stopped. Logs are in /var/log/blocked_process_monitor
```

when the process exits.

Press:

``` text
Ctrl+C
```

to stop it.

------------------------------------------------------------------------

# Option 2: Background

Run:

``` bash
sudo nohup /usr/local/bin/system_process_monitor.py \
  > /var/log/system_process_monitor_console.log 2>&1 &
```

The script will continue running after the terminal session is
disconnected.

The shell PID can be checked with:

``` bash
pgrep -af system_process_monitor.py
```

or:

``` bash
ps -ef | grep system_process_monitor.py
```

------------------------------------------------------------------------

# Stopping the Monitor

## Graceful Stop

Find the PID:

``` bash
pgrep -af system_process_monitor.py
```

Example:

``` text
12345 python3 /usr/local/bin/system_process_monitor.py
```

Stop it:

``` bash
sudo kill 12345
```

The script handles `SIGTERM` and performs a graceful shutdown.

It attempts to:

1.  Stop monitoring loops
2.  Allow current monitoring operations to finish
3.  Drain pending log messages
4.  Stop the writer/rotation threads
5.  Close the active log file

------------------------------------------------------------------------

## Stop From Foreground

If running directly:

``` bash
sudo /usr/local/bin/system_process_monitor.py
```

press:

``` text
Ctrl+C
```

This sends `SIGINT` and triggers the same shutdown handling.

------------------------------------------------------------------------

## Force Stop

Only if the process does not respond:

``` bash
sudo kill -9 <PID>
```

A forced `SIGKILL` does not allow the script to perform its normal
shutdown procedure.

Therefore, use normal `kill` or `Ctrl+C` whenever possible.

------------------------------------------------------------------------

# Checking Logs

List logs:

``` bash
ls -lh /var/log/blocked_process_monitor/
```

Follow the active log:

``` bash
tail -f /var/log/blocked_process_monitor/system_monitor_*.log
```

------------------------------------------------------------------------

# Search for Blocked Processes

``` bash
grep -i "D-STATE" /var/log/blocked_process_monitor/*.log
```

Search for wait channels:

``` bash
grep -i "WCHAN" /var/log/blocked_process_monitor/*.log
```

Search compressed logs:

``` bash
zgrep -Ei "D-STATE|BLOCKED|WCHAN" \
  /var/log/blocked_process_monitor/*.log.gz
```

------------------------------------------------------------------------

# Find Heavy CPU Processes

``` bash
grep -i "TOP CPU PROCESSES" \
  /var/log/blocked_process_monitor/*.log
```

------------------------------------------------------------------------

# Find Heavy Memory Processes

``` bash
grep -i "TOP MEMORY PROCESSES" \
  /var/log/blocked_process_monitor/*.log
```

------------------------------------------------------------------------

# Find Heavy I/O Processes

``` bash
grep -i "TOP I/O PROCESSES" \
  /var/log/blocked_process_monitor/*.log
```

For compressed logs:

``` bash
zgrep -i "TOP I/O PROCESSES" \
  /var/log/blocked_process_monitor/*.log.gz
```

------------------------------------------------------------------------

# Check System Load and Process Growth

Search:

``` bash
grep -i "SYSTEM SUMMARY" \
  /var/log/blocked_process_monitor/*.log
```

The most important fields for process-growth investigations are:

``` text
LOAD_1M
LOAD_5M
LOAD_15M
PROCESS_COUNT
THREAD_COUNT
D_STATE_COUNT
```

For example:

``` text
06:30
PROCESS_COUNT : 2916
LOAD_1M       : 47.13

06:40
PROCESS_COUNT : 15225
LOAD_1M       : 2498.89
```

This type of timeline can help identify when the system transitioned
from normal/high activity into an extreme process/load condition.

------------------------------------------------------------------------

# Typical Troubleshooting Workflow

When a server becomes slow, use the collected data in chronological
order.

## Step 1 - Check system load

Look for:

``` text
LOAD_1M
LOAD_5M
LOAD_15M
```

Compare the load against:

``` text
CPU_COUNT
```

Do not interpret load alone as CPU utilization. Linux load can also
increase due to tasks waiting in uninterruptible states.

------------------------------------------------------------------------

## Step 2 - Check process count

Look for:

``` text
PROCESS_COUNT
```

A sudden increase can indicate:

-   Process spawning
-   Application worker creation
-   Process leaks
-   Repeated command execution
-   Service restart loops

The script records the observation; further investigation is required to
identify the application responsible.

------------------------------------------------------------------------

## Step 3 - Check thread count

Look for:

``` text
THREAD_COUNT
```

A sudden thread increase can indicate application-level thread growth.

Compare:

``` text
PROCESS_COUNT
THREAD_COUNT
```

over time.

------------------------------------------------------------------------

## Step 4 - Check D-state processes

Look for:

``` text
D_STATE_COUNT
```

Then inspect:

``` text
D-STATE / BLOCKED PROCESS
```

entries.

Important fields include:

``` text
PID
PPID
COMMAND
BLOCKED_SECONDS
WCHAN
READ_BYTES
WRITE_BYTES
OPEN_FILES/DEVICES
```

------------------------------------------------------------------------

## Step 5 - Check process-level I/O

Review:

``` text
TOP I/O PROCESSES
```

Look for processes with high:

``` text
READ_MB/s
WRITE_MB/s
```

Then correlate them with D-state entries.

------------------------------------------------------------------------

## Step 6 - Check CPU

Review:

``` text
TOP CPU PROCESSES
```

Identify whether one or more processes are responsible for high CPU
activity.

------------------------------------------------------------------------

## Step 7 - Check memory

Review:

``` text
TOP MEMORY PROCESSES
```

and:

``` text
MEM_AVAILABLE_MB
MEM_USED_PCT
```

This can help identify memory-heavy processes.

------------------------------------------------------------------------

# Example Incident Investigation

Suppose the server is reported as slow at 06:40.

The logs might show:

``` text
06:30
LOAD_1M       : 47.13
PROCESS_COUNT : 2916

06:35
D_STATE_COUNT : 120

06:40
LOAD_1M       : 2498.89
PROCESS_COUNT : 15225
THREAD_COUNT  : 18000
D_STATE_COUNT : 325
```

The next step would be to correlate these observations with:

``` text
TOP CPU PROCESSES
TOP MEMORY PROCESSES
TOP I/O PROCESSES
D-STATE / BLOCKED PROCESS
```

The script does not automatically declare a root cause. It provides
timestamped evidence that can be correlated with application logs,
kernel logs, storage metrics, systemd events, and other monitoring
systems.

------------------------------------------------------------------------

# Configuration

The main configuration values are near the beginning of the script.

## Log Directory

``` python
LOG_DIR = "/var/log/blocked_process_monitor"
```

Change this if logs need to be stored elsewhere.

------------------------------------------------------------------------

## Monitoring Interval

``` python
SCAN_INTERVAL = 5
```

The default is 5 seconds.

For example:

``` python
SCAN_INTERVAL = 10
```

collects approximately every 10 seconds.

A shorter interval produces more frequent observations and can increase
monitoring overhead.

------------------------------------------------------------------------

## Log Rotation

``` python
ROTATE_SECONDS = 2 * 60 * 60
```

Default:

``` text
2 hours
```

For a 1-hour rotation:

``` python
ROTATE_SECONDS = 60 * 60
```

------------------------------------------------------------------------

## D-State Threshold

``` python
HANG_THRESHOLD_SECONDS = 10
```

Default:

``` text
10 seconds
```

A process must remain in `D` state for at least this duration before a
blocked-process record is generated.

------------------------------------------------------------------------

## Number of Top Processes

``` python
TOP_N = 15
```

This controls the number of CPU, memory, and I/O processes recorded in
each collection cycle.

------------------------------------------------------------------------

# Security and Permissions

The script reads process information from `/proc`.

Some `/proc` information can be restricted depending on:

-   User ID
-   Kernel configuration
-   `/proc` mount options
-   Distribution security settings

For complete visibility, run as root:

``` bash
sudo /usr/local/bin/system_process_monitor.py
```

The script itself does not modify processes, kill processes, change CPU
scheduling, change storage configuration, or alter application
configuration.

Its primary operation is observation and log collection.

------------------------------------------------------------------------

# Resource Usage

The monitor performs periodic scans of `/proc`.

Because CPU, memory, I/O, blocked-process, and system monitoring run as
separate threads, each collector independently scans process
information.

This provides concurrent collection, but it also means the script
performs multiple `/proc` scans during each monitoring interval.

For this reason:

-   Use a reasonable `SCAN_INTERVAL`
-   Avoid unnecessarily aggressive intervals on very large systems
-   Monitor the monitor itself if deploying it permanently on extremely
    busy hosts

The script uses only standard Python libraries and does not require
external agents.

------------------------------------------------------------------------

# Limitations

The script is intended as a troubleshooting and evidence-collection
utility.

It does not:

-   Determine the root cause automatically
-   Kill or restart blocked processes
-   Restart services
-   Change kernel parameters
-   Change storage configuration
-   Collect historical data that existed before the monitor was started
-   Replace `sar`, `pidstat`, `iostat`, `vmstat`, `top`, or enterprise
    monitoring systems
-   Identify the underlying storage device responsible for every I/O
    wait
-   Automatically associate every D-state process with a specific
    storage device

For a complete RCA, correlate the generated logs with:

-   `journalctl`
-   Kernel logs
-   Application logs
-   `iostat`
-   `vmstat`
-   `pidstat`
-   Storage/LVM/device-mapper information
-   Cloud infrastructure metrics
-   Network/storage service logs

------------------------------------------------------------------------

# Recommended Production Usage

For an incident investigation, start the monitor before reproducing or
waiting for the performance problem:

``` bash
sudo nohup /usr/local/bin/system_process_monitor.py \
  > /var/log/system_process_monitor_console.log 2>&1 &
```

Then verify:

``` bash
pgrep -af system_process_monitor.py
```

Watch the active log:

``` bash
tail -f /var/log/blocked_process_monitor/system_monitor_*.log
```

After the incident:

``` bash
ls -lh /var/log/blocked_process_monitor/
```

Collect the generated `.log` and `.log.gz` files together with other
troubleshooting artifacts.

Stop the monitor:

``` bash
sudo kill $(pgrep -f '/usr/local/bin/system_process_monitor.py')
```

------------------------------------------------------------------------

# Quick Reference

## Install

``` bash
sudo cp system_process_monitor.py /usr/local/bin/system_process_monitor.py
sudo chmod 750 /usr/local/bin/system_process_monitor.py
sudo mkdir -p /var/log/blocked_process_monitor
```

## Start

``` bash
sudo /usr/local/bin/system_process_monitor.py
```

## Start in background

``` bash
sudo nohup /usr/local/bin/system_process_monitor.py \
  > /var/log/system_process_monitor_console.log 2>&1 &
```

## Check status

``` bash
pgrep -af system_process_monitor.py
```

## Stop

``` bash
sudo kill <PID>
```

## Follow logs

``` bash
tail -f /var/log/blocked_process_monitor/system_monitor_*.log
```

## Search D-state processes

``` bash
grep -i "D-STATE" /var/log/blocked_process_monitor/*.log
```

## Search I/O

``` bash
grep -i "TOP I/O PROCESSES" /var/log/blocked_process_monitor/*.log
```

## Search CPU

``` bash
grep -i "TOP CPU PROCESSES" /var/log/blocked_process_monitor/*.log
```

## Search memory

``` bash
grep -i "TOP MEMORY PROCESSES" /var/log/blocked_process_monitor/*.log
```

## Search compressed logs

``` bash
zgrep -Ei "D-STATE|BLOCKED|TOP I/O|TOP CPU|TOP MEMORY" \
  /var/log/blocked_process_monitor/*.log.gz
```

------------------------------------------------------------------------

# Repository Structure

A simple GitHub repository can use:

``` text
system-process-monitor/
├── system_process_monitor.py
├── README.md
└── LICENSE
```

Optional additions:

``` text
system-process-monitor/
├── system_process_monitor.py
├── README.md
├── LICENSE
├── systemd/
│   └── system-process-monitor.service
└── docs/
    └── troubleshooting.md
```

------------------------------------------------------------------------

# Intended Use

This utility is intended primarily for Linux performance troubleshooting
and incident evidence collection.

It is especially useful when investigating combinations of:

``` text
High Load
    +
Process/Thread Growth
    +
High I/O
    +
D-State Processes
    +
High CPU
    +
High Memory
```

The timestamped records allow these conditions to be correlated over
time rather than relying only on point-in-time commands executed after
the incident has already occurred.

------------------------------------------------------------------------

License

This project is licensed under the MIT License.

Copyright (c) 2026 Chenthil Lingamurthy

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

SPDX-License-Identifier: MIT
