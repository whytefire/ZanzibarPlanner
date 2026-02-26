@echo off
cd /d "c:\GIT\ZanzibarPlanner\deal_finder"
python deal_finder.py --no-browser >> results\scan_log.txt 2>&1
