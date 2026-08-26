Requirements:
- Goldshell SC Lite
- firmware 2.2.0
- jq
- curl
- browser login to miner

Get JWT/token:
1. Open miner UI in browser -> go to hidden "debug" page with 192.168.x.y/#/debug
2. Log in
3. F12/ctrl+shift+I for browser tools -> Go to "Console"
4. Enter: localStorage.getItem('token')
5. Head back to your terminal and enter: export TOKEN='...' (insert what you copied from your browser)

You will periodically need to use the browser to reauthenticate - commands in your terminal will stop working otherwise as the token expires.

Set miner IP:
export MINER_IP='192.168.x.x'
