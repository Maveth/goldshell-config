Requirements:
- Goldshell SC Lite
- firmware 2.2.0
- jq
- curl
- browser login to miner

Get JWT:
1. Open miner UI
2. Log in
3. F12 -> Console
4. localStorage.getItem('token')
5. export TOKEN='...'

Set miner IP:
export MINER_IP='192.168.x.x'
